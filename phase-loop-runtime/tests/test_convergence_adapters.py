"""SL-3 falsifiers for the bounded provider adapters (EC-RUNTIME-3)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from phase_loop_runtime.convergence.adapters import (
    AdapterExecutionRequest, run_claude_adapter, run_codex_adapter, run_outside_agent_adapter,
)
from phase_loop_runtime.convergence.contracts import AdmissionRequest
from phase_loop_runtime.train_ledger import ConvergenceResultStatus

from _runtime_tdd_guard import RuntimeCapabilityMissing, require_source_capability
from runtime_content_tdd_adapter import RUNTIME_CASES, run_mapped_case

_SECRET = "ghp_1111111111111111111111111111111111"
_FROZEN_STATUSES = ("completed", "verified", "blocked", "needs_clarification", "degraded", "failed")


def _admission(**overrides) -> AdmissionRequest:
    value = dict(
        attempt_id="a", lease_epoch=1, fence_token="fence", approval_digest="approval",
        expected_version_predicate="head==abc", authority_domain_scope="repo",
        idempotency_key="key",
    )
    value.update(overrides)
    return AdmissionRequest(**value)


def _request(argv, cwd: Path, *, timeout: float = 10.0, **overrides) -> AdapterExecutionRequest:
    value = dict(
        attempt_id="a", admission=_admission(), argv=tuple(argv), cwd=cwd,
        timeout_seconds=timeout, allowed_action="execute",
    )
    value.update(overrides)
    return AdapterExecutionRequest(**value)


def _install(bin_dir: Path, name: str, body: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return script


def _emit(payload: dict) -> str:
    return f"printf '%s' '{json.dumps(payload)}'"


# ---------------------------------------------------------------------------
# Retained skeleton behaviour and the EC-RUNTIME-3 path-entered control


def test_adapter_rejects_out_of_bounds_command(tmp_path: Path):
    request = _request(("not-codex",), tmp_path)
    assert run_codex_adapter(request).status.value == "blocked"


def test_each_provider_executes_one_bounded_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """EC-RUNTIME-3 path-entered control: one valid bounded run per provider."""
    bin_dir = tmp_path / "bin"
    for name in ("codex", "claude", "outside-agent"):
        _install(bin_dir, name, _emit({"status": "completed"}), monkeypatch)
    for name, runner in (("codex", run_codex_adapter), ("claude", run_claude_adapter)):
        envelope = runner(_request((name,), tmp_path))
        assert envelope.status is ConvergenceResultStatus.COMPLETED
        assert envelope.attempt_id == "a"


def test_bounded_request_rejects_unbounded_or_unowned_shapes(tmp_path: Path):
    with pytest.raises(ValueError):
        _request((), tmp_path)
    with pytest.raises(ValueError):
        _request(("codex",), tmp_path, timeout=0)
    with pytest.raises(ValueError):
        _request(("codex",), tmp_path, allowed_action="publish")
    with pytest.raises(ValueError):
        _request(("codex",), tmp_path, attempt_id="other")


# ---------------------------------------------------------------------------
# SL-3 mapped falsifiers


def test_executable_identity_is_exact_not_a_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``codex-rogue`` shares codex's prefix but is a different executable."""
    _install(tmp_path / "bin", "codex-rogue", _emit({"status": "completed"}), monkeypatch)
    envelope = run_codex_adapter(_request(("codex-rogue",), tmp_path))

    def probe():
        if envelope.status is not ConvergenceResultStatus.BLOCKED:
            raise RuntimeCapabilityMissing("provider identity is matched by prefix, not exactly")

    def assertion():
        assert envelope.status is ConvergenceResultStatus.BLOCKED
        assert envelope.attempt_id == "a"

    run_mapped_case("adapters.exact-executable-identity", probe=probe, assertion=assertion)


def test_child_environment_is_credential_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mutation credentials and subscription escapes must never reach the child."""
    leaked = tmp_path / "env.txt"
    _install(tmp_path / "bin", "codex", f"env > {leaked}; {_emit({'status': 'completed'})}", monkeypatch)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(name, _SECRET)
    run_codex_adapter(_request(("codex",), tmp_path))
    observed = leaked.read_text(encoding="utf-8") if leaked.is_file() else ""

    def probe():
        if any(f"{name}=" in observed for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_BASE_URL")):
            raise RuntimeCapabilityMissing("the child environment still carries credential material")

    def assertion():
        assert observed, "the bounded child must actually run"
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
            assert f"{name}=" not in observed, f"{name} reached the adapter child"

    run_mapped_case("adapters.environment-is-credential-stripped", probe=probe, assertion=assertion)


def test_timeout_reclaims_the_child_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A timed-out adapter must reclaim its whole process group, not just the child."""
    case = RUNTIME_CASES["adapters.timeout-reclaims-process-group"]
    _install(tmp_path / "bin", "codex", "sleep 30", monkeypatch)
    killed: list[int] = []

    def probe():
        require_source_capability(case.production_path, case.symbol, "killpg")

    def assertion():
        real_killpg = os.killpg

        def recording_killpg(pgid, signal_number):
            killed.append(pgid)
            return real_killpg(pgid, signal_number)

        monkeypatch.setattr(os, "killpg", recording_killpg)
        started = time.monotonic()
        envelope = run_codex_adapter(_request(("codex",), tmp_path, timeout=0.5))
        monkeypatch.undo()
        assert envelope.status is ConvergenceResultStatus.DEGRADED
        assert envelope.attempt_id == "a"
        assert time.monotonic() - started < 20
        assert killed, "the timed-out child's process group must be reclaimed"

    run_mapped_case("adapters.timeout-reclaims-process-group", probe=probe, assertion=assertion)


def test_blank_expected_version_predicate_is_rejected(tmp_path: Path):
    """A whitespace predicate is truthy but is not a nonempty exact-version binding."""
    blank = AdmissionRequest("a", 1, "fence", "approval", "   ", "repo", "key")
    raised = False
    try:
        _request(("codex",), tmp_path, admission=blank)
    except ValueError:
        raised = True

    def probe():
        if not raised:
            raise RuntimeCapabilityMissing("a blank expected-version predicate is accepted")

    def assertion():
        assert raised
        assert _request(("codex",), tmp_path).admission.expected_version_predicate.strip()

    run_mapped_case("adapters.expected-version-predicate-is-bound", probe=probe, assertion=assertion)


def test_malformed_adapter_output_is_not_reported_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unparseable provider output must never be laundered into ``completed``."""
    _install(tmp_path / "bin", "codex", "printf '%s' 'not json at all'", monkeypatch)
    envelope = run_codex_adapter(_request(("codex",), tmp_path))

    def probe():
        if envelope.status in (ConvergenceResultStatus.COMPLETED, ConvergenceResultStatus.VERIFIED):
            raise RuntimeCapabilityMissing("malformed output is reported as success")

    def assertion():
        assert envelope.status in (
            ConvergenceResultStatus.BLOCKED,
            ConvergenceResultStatus.DEGRADED,
            ConvergenceResultStatus.FAILED,
        )
        assert envelope.attempt_id == "a"

    run_mapped_case("adapters.malformed-output-is-not-success", probe=probe, assertion=assertion)


def test_unvalidated_third_party_submission_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``run_outside_agent_adapter`` with no validated submission must block, not execute.

    The name deliberately avoids the ``outside_agent`` substring: the frozen
    corpus in ``test_outside_agent_canonical_corpus.py`` is owned by another
    phase and closes over every collected node id matching it.
    """
    _install(tmp_path / "bin", "outside-agent", _emit({"status": "completed"}), monkeypatch)
    envelope = run_outside_agent_adapter(_request(("outside-agent",), tmp_path))

    def probe():
        if envelope.status is not ConvergenceResultStatus.BLOCKED:
            raise RuntimeCapabilityMissing("a missing submission bypasses the conformance validator")

    def assertion():
        assert envelope.status is ConvergenceResultStatus.BLOCKED
        assert envelope.attempt_id == "a"
        assert run_outside_agent_adapter(
            _request(("outside-agent",), tmp_path), {"not": "conformant"}
        ).status is ConvergenceResultStatus.BLOCKED

    run_mapped_case("adapters.outside-agent-requires-conformance", probe=probe, assertion=assertion)


def _status_matrix(runner, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple]:
    observed: dict[str, tuple] = {}
    for status in _FROZEN_STATUSES:
        bin_dir = tmp_path / f"bin-{status}"
        _install(bin_dir, name, _emit({"status": status, "note": _SECRET}), monkeypatch)
        envelope = runner(_request((name,), tmp_path))
        observed[status] = (
            envelope.status.value,
            envelope.attempt_id,
            _SECRET in (envelope.detail or ""),
        )
    return observed


def test_codex_envelope_is_frozen_and_metadata_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    observed = _status_matrix(run_codex_adapter, "codex", tmp_path, monkeypatch)

    def probe():
        if any(leaked for _status, _attempt, leaked in observed.values()):
            raise RuntimeCapabilityMissing("adapter diagnostics are not kept metadata-only")

    def assertion():
        for status in _FROZEN_STATUSES:
            value, attempt, leaked = observed[status]
            assert value == status, f"codex did not preserve the frozen {status} status"
            assert attempt == "a"
            assert not leaked

    run_mapped_case("adapters.codex-binds-provider-identity", probe=probe, assertion=assertion)


def test_claude_envelope_matches_codex_for_every_frozen_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    codex = _status_matrix(run_codex_adapter, "codex", tmp_path / "codex", monkeypatch)
    claude = _status_matrix(run_claude_adapter, "claude", tmp_path / "claude", monkeypatch)

    def probe():
        if any(leaked for _status, _attempt, leaked in claude.values()):
            raise RuntimeCapabilityMissing("adapter diagnostics are not kept metadata-only")

    def assertion():
        assert claude == codex, "all adapters must return the same frozen envelope"
        for status in _FROZEN_STATUSES:
            assert claude[status] == (status, "a", False)

    run_mapped_case("adapters.claude-binds-provider-identity", probe=probe, assertion=assertion)

# WORKER fixtures are offline, and do not claim provider qualification.
import hashlib
import sys
import threading
from phase_loop_runtime.convergence.adapters import base as capture_base


def _capture(tmp_path, source, *, cap=4096, stdin=b"", timeout=2, cancel=None, before_spawn=lambda: None):
    request = capture_base.CaptureRequest("fixture", (sys.executable, "-I", "-c", source),
        tmp_path, timeout, stdin, cap, capture_base.worker_child_environment(frozenset()))
    return capture_base.run_bounded_capture(request, before_spawn=before_spawn,
                                            cancel=cancel or threading.Event())


@pytest.mark.parametrize("length", [0, 20, 4096, 8192])
def test_worker_capture_full_stream_digests(tmp_path, length):
    source = f'import os; os.write(1, bytes(range(256))*{length // 256}); os.write(2,b"e"*100000)'
    result = _capture(tmp_path, source)
    expected = bytes(range(256)) * (length // 256)
    assert result.stdout == capture_base.StreamDigest(hashlib.sha256(expected).hexdigest(), len(expected))
    assert result.stderr == capture_base.StreamDigest(hashlib.sha256(b"e" * 100000).hexdigest(), 100000)
    assert result.streams_complete
    assert result.proposal_overflow == (len(expected) > 4096)
    assert result.proposal == (expected if len(expected) <= 4096 else None)
    assert result.spawn_count == 1 and result.termination == "completed" and result.exit_code == 0


def test_worker_instruction_pipe_and_epipe(tmp_path):
    sentinel = b"fixture-instruction-sentinel"
    result = _capture(tmp_path, 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())', stdin=sentinel)
    assert result.proposal == sentinel and result.stdin_delivered
    result = _capture(tmp_path, 'import os,time; os.close(0); time.sleep(.1)', stdin=b"x" * 1000000)
    assert not result.stdin_delivered


@pytest.mark.parametrize("kind", ["deadline", "cancel", "failed_exec", "refuse", "raise"])
def test_worker_capture_lifecycle(tmp_path, kind):
    cancel = threading.Event()
    if kind == "cancel":
        cancel.set()
    before = lambda: capture_base.SpawnRefused("fixture")
    if kind == "raise":
        def before():
            raise ValueError("fixture")
    if kind in ("refuse", "raise"):
        result = _capture(tmp_path, 'raise AssertionError("must not run")', before_spawn=before)
        assert isinstance(result, capture_base.SpawnRefused)
        return
    if kind == "failed_exec":
        request = capture_base.CaptureRequest("fixture", (str(tmp_path / "absent"),), tmp_path, 1, b"", 10, {})
        result = capture_base.run_bounded_capture(request, before_spawn=lambda: None, cancel=cancel)
        assert result.termination == "failed_to_start" and result.spawn_count == 1
        return
    result = _capture(tmp_path, 'import time; time.sleep(30)', timeout=.2, cancel=cancel)
    assert result.termination == ("cancelled" if kind == "cancel" else "timed_out")
    assert result.signal == "SIGKILL" and result.proposal == b""
    assert result.duration_ns < 2_000_000_000


@pytest.mark.parametrize("name", sorted(capture_base.WORKER_ENV_DROP) +
                         ["GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GH_TOKEN", "OPENAI_API_KEY"])
def test_worker_environment_scrub(monkeypatch, name):
    monkeypatch.setenv(name, "fixture-value")
    assert name not in capture_base.worker_child_environment(frozenset({name}))
    assert set(capture_base.worker_child_environment(frozenset())) <= {"TMPDIR", "CLAUDE_CODE_TMPDIR", capture_base.sandbox_policy.CHILD_SCRATCH_MARKER}


def test_worker_group_cleanup_and_escaped_pipe(tmp_path):
    import signal
    import time
    pidfile = tmp_path / "escape"
    restore = _adopt_worker_children()
    source = ('import os,time; pid=os.fork(); '
              '\nif pid == 0:\n os.setsid(); '
              f'open({str(pidfile)!r},"w").write(str(os.getpid())); time.sleep(30)'
              '\nelse:\n time.sleep(.1)')
    try:
        started = time.monotonic()
        result = _capture(tmp_path, source, timeout=.4)
        assert result.termination == "completed" and not result.streams_complete
        assert time.monotonic() - started < 2
    finally:
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text())
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except ProcessLookupError:
                pass
        restore()


def _adopt_worker_children():
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert library.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert library.prctl(36, 1, 0, 0, 0) == 0
    return lambda: library.prctl(36, previous.value, 0, 0, 0)


CAPTURE_CONTROLS = {
    "proposal-cap": ('overflow = counts["stdout"] > request.proposal_cap', 'overflow = False'),
    "stderr-digest": ('hashes[key.data].update(chunk)', 'hashes[key.data].update(chunk if key.data == "stdout" else b"")'),
    "deadline-arm": ('deadline = time.monotonic() + request.timeout_seconds', 'deadline = time.monotonic() + 10'),
    "drain-deadline": ('if remaining <= 0:\n                if not reaped:\n                    termination, by, sig = "timed_out", "harness", "SIGKILL"\n                break', 'if remaining <= 0:\n                remaining = .05'),
    "cancel-kill": ('elif cancel.is_set():', 'elif False and cancel.is_set():'),
    "group-reclaim": ('os.killpg(process.pid, signal.SIGKILL)', 'None'),
    "stdin-channel": ('request.stdin[offset:offset + 65536]', 'b""'),
    "allowlist": ('and key in (allow | {"TMPDIR", "CLAUDE_CODE_TMPDIR", sandbox_policy.CHILD_SCRATCH_MARKER})', ''),
    "before-spawn": ('if refusal is not None:', 'if False and refusal is not None:'),
}
for _name in sorted(capture_base.WORKER_ENV_DROP):
    CAPTURE_CONTROLS["drop-" + _name] = (f'"{_name}"', '"unused-fixture-name"')
for _prefix in capture_base.WORKER_ENV_DROP_PREFIXES:
    CAPTURE_CONTROLS["prefix-" + _prefix] = (f'"{_prefix}"', '"unused-fixture-prefix"')


def _capture_source_copy(monkeypatch, control):
    import types
    source = Path(capture_base.__file__).read_text()
    old, new = CAPTURE_CONTROLS[control]
    assert old in source
    module = types.ModuleType("phase_loop_runtime.convergence.adapters._capture_copy")
    module.__package__ = capture_base.__package__
    module.__file__ = capture_base.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    prefix, tail = source.split("# Patch-return capture", 1)
    assert old in tail
    exec(compile(prefix + "# Patch-return capture" + tail.replace(old, new, 1), module.__file__, "exec"), module.__dict__)
    return module


def _capture_control_witness(module, control, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker
    event = threading.Event()
    source, stdin, cap, duration = 'import os; os.write(1,b"x"*200); os.write(2,b"err")', b"", 100, .15
    before = lambda: None
    if control in ("deadline-arm", "cancel-kill", "group-reclaim"):
        source = 'import time; time.sleep(.3)'
    if control == "cancel-kill":
        event.set()
    if control == "stdin-channel":
        stdin = b"fixture-instructions"
        source = 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'
    if control == "before-spawn":
        before = lambda: module.SpawnRefused("fixture-refused")
    pidfile = tmp_path / "escape-mutant"
    if control == "drain-deadline":
        source = f'import os,time; pid=os.fork()\nif pid==0:\n os.setsid(); open({str(pidfile)!r},"w").write(str(os.getpid())); time.sleep(.3); os._exit(0)\nelse:\n time.sleep(.03)'
    environment = module.worker_child_environment(frozenset())
    if control.startswith(("drop-", "prefix-")) or control == "allowlist":
        name = (control[5:] if control.startswith("drop-") else
                control[7:] + "0" if control.startswith("prefix-") else "WORKER_FIXTURE_UNLISTED")
        monkeypatch.setattr(module, "_child_environment", lambda: {name: "fixture-value"})
        environment = module.worker_child_environment(frozenset() if control == "allowlist" else frozenset({name}))
        source = 'import os; os.write(1, b"present" if ' + repr(name) + ' in os.environ else b"absent")'
    count = []
    original = panel_invoker.launch_owned
    def launch(*args, **kwargs):
        count.append(1)
        assert stdin.decode() not in " ".join(args[0]) if stdin else True
        return original(*args, **kwargs)
    monkeypatch.setattr(panel_invoker, "launch_owned", launch)
    kills = []
    original_kill = os.killpg
    def killed(pid, sig):
        kills.append(pid)
        return original_kill(pid, sig)
    monkeypatch.setattr(os, "killpg", killed)
    result = module.run_bounded_capture(module.CaptureRequest("fixture", (sys.executable, "-I", "-c", source),
        tmp_path, duration, stdin, cap, environment), before_spawn=before, cancel=event)
    if control == "before-spawn":
        assert isinstance(result, module.SpawnRefused) and not count
    elif control.startswith(("drop-", "prefix-")) or control == "allowlist":
        assert result.proposal == b"absent"
    elif control == "deadline-arm":
        assert result.termination == "timed_out"
    elif control == "cancel-kill":
        assert result.termination == "cancelled"
    elif control == "group-reclaim":
        assert kills
    elif control == "stdin-channel":
        assert result.stdin_delivered and result.proposal == stdin
    elif control == "drain-deadline":
        assert not result.streams_complete
    else:
        assert result.proposal_overflow and result.proposal is None
        assert result.stderr.sha256 == hashlib.sha256(b"err").hexdigest()


@pytest.mark.parametrize("control", sorted(CAPTURE_CONTROLS))
@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_worker_capture_source_controls(tmp_path, monkeypatch, control, mutated):
    module = _capture_source_copy(monkeypatch, control) if mutated else capture_base
    restore = _adopt_worker_children()
    try:
        if mutated:
            with pytest.raises(AssertionError):
                _capture_control_witness(module, control, tmp_path, monkeypatch)
        else:
            _capture_control_witness(module, control, tmp_path, monkeypatch)
    finally:
        pidfile = tmp_path / "escape-mutant"
        if pidfile.exists():
            os.waitpid(int(pidfile.read_text()), 0)
        restore()


@pytest.mark.parametrize("status", _FROZEN_STATUSES)
def test_worker_preserves_convergence_status_and_detail(tmp_path, monkeypatch, status):
    script = _install(tmp_path / "bin", "codex", _emit({"status": status}), monkeypatch)
    result = run_codex_adapter(_request((str(script),), tmp_path))
    assert result.status.value == status and result.detail == capture_base._DETAIL_OK


@pytest.mark.parametrize("mode,expected,detail", [
    ("oversized", "blocked", capture_base._DETAIL_OVERFLOW),
    ("binary", "blocked", capture_base._DETAIL_MALFORMED),
    ("nonzero", "failed", capture_base._DETAIL_NONZERO),
    ("timeout", "degraded", capture_base._DETAIL_TIMEOUT),
    ("malformed", "blocked", capture_base._DETAIL_MALFORMED),
])
def test_worker_preserves_convergence_bounds(tmp_path, monkeypatch, mode, expected, detail):
    bodies = {"oversized": 'head -c 65537 /dev/zero', "binary": "printf '\\377'",
              "nonzero": "exit 7", "timeout": "sleep .3", "malformed": "printf fixture"}
    script = _install(tmp_path / "bin", "codex", bodies[mode], monkeypatch)
    result = run_codex_adapter(_request((str(script),), tmp_path, timeout=.1))
    assert result.status.value == expected and result.detail == detail


def test_worker_preserves_convergence_devnull_stdin(tmp_path, monkeypatch):
    import subprocess
    from phase_loop_runtime import panel_invoker
    original = panel_invoker.launch_owned
    observed = []
    def launched(*args, **kwargs):
        observed.append(kwargs["stdin"])
        return original(*args, **kwargs)
    monkeypatch.setattr(panel_invoker, "launch_owned", launched)
    script = _install(tmp_path / "bin", "codex", _emit({"status": "completed"}), monkeypatch)
    assert run_codex_adapter(_request((str(script),), tmp_path)).status.value == "completed"
    assert observed == [subprocess.DEVNULL]


@pytest.mark.parametrize("kind,expected,detail", [
    ("cwd", "blocked", capture_base._DETAIL_BAD_CWD),
    ("exec", "failed", capture_base._DETAIL_SPAWN_FAILED),
    ("scratch", "failed", capture_base._DETAIL_NO_SCRATCH),
    ("cleanup", "degraded", capture_base._DETAIL_CLEANUP),
])
def test_worker_preserves_convergence_refusal_details(tmp_path, monkeypatch, kind, expected, detail):
    script = _install(tmp_path / "bin", "codex", _emit({"status": "completed"}), monkeypatch)
    if kind == "scratch":
        def unavailable():
            raise capture_base.sandbox_policy.SandboxSpaceError("synthetic scratch unavailable")
        monkeypatch.setattr(capture_base, "_child_environment", unavailable)
    if kind == "cleanup":
        def unavailable(*args):
            raise PermissionError("synthetic cleanup unavailable")
        monkeypatch.setattr(os, "killpg", unavailable)
    result = run_codex_adapter(_request((str(tmp_path / "codex") if kind == "exec" else str(script),),
                                       tmp_path / "missing" if kind == "cwd" else tmp_path))
    assert result.status.value == expected and result.detail == detail


@pytest.mark.parametrize("size,expected", [(65536, "completed"), (65537, "blocked")])
def test_worker_preserves_convergence_exact_cap(tmp_path, monkeypatch, size, expected):
    script = _install(tmp_path / "bin", "codex",
        f"{sys.executable} -I -c 'import os; data=b\"{{\\\"status\\\":\\\"completed\\\"}}\"; os.write(1,data+b\" \"*({size}-len(data)))'", monkeypatch)
    assert run_codex_adapter(_request((str(script),), tmp_path)).status.value == expected


@pytest.mark.parametrize("exception", [ValueError, KeyboardInterrupt, SystemExit])
def test_worker_before_spawn_exception_never_launches(tmp_path, monkeypatch, exception):
    from phase_loop_runtime import panel_invoker
    launches = []
    def launch(*args, **kwargs):
        launches.append(1)
        raise AssertionError("spawn after refused callback")
    monkeypatch.setattr(panel_invoker, "launch_owned", launch)
    def before():
        raise exception("synthetic callback")
    result = _capture(tmp_path, "pass", before_spawn=before)
    assert isinstance(result, capture_base.SpawnRefused) and launches == []


def test_worker_deadline_between_clock_reads(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker
    original = panel_invoker.launch_owned
    spawned = []
    def launch(*args, **kwargs):
        result = original(*args, **kwargs)
        spawned.append(1)
        return result
    monkeypatch.setattr(panel_invoker, "launch_owned", launch)
    ticks = []
    real_clock = time.monotonic
    initial = real_clock()
    def clock():
        if not spawned:
            return initial
        ticks.append(1)
        return initial if len(ticks) == 1 else initial + 10
    monkeypatch.setattr(time, "monotonic", clock)
    result = _capture(tmp_path, "import time; time.sleep(5)", timeout=1)
    assert result.termination == "timed_out" and result.terminated_by == "harness" and result.signal == "SIGKILL"
