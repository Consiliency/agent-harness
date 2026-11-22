"""JEVHOST launcher merge controls (S2, S3, L4, [B4], [P2]); no provider execution.

Each case pins one rule of the launcher three-way merge: the usage probe's place
relative to ``dependency.validate_command``, the probe as an owned launch, redaction
before every ``consume`` sink, the native-Windows review refusal and the keywords the
two ``launch()`` recursions forward.
"""

import contextlib
import os
import subprocess
import sys
from dataclasses import replace

import pytest

from phase_loop_runtime import executable_dependency_startup, launcher, panel_invoker
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime.launcher import LaunchResult, LaunchSpec
from phase_loop_runtime.models import InjectionMetadata, PromptBundle

DISABLED = {"capture": "disabled", "reason": "unsupported_path_or_probe"}


def codex_spec(tmp_path, *, product_action=None):
    bundle = PromptBundle("workflow", "SYNTHETIC_TASK", "inline", product_action=product_action)
    return LaunchSpec(executor="codex", command=["codex", "exec", "--json", bundle.render_context()],
                      prompt_bundle=bundle, injection_metadata=InjectionMetadata("codex", "inline"),
                      delivery_mode="inline", dispatch_decision=None, available=True,
                      selected_model="model-a", effective_effort="high", wrapped_cwd=str(tmp_path))


class RecordingDependency:
    """A bound dependency that records each validation, and optionally refuses one."""

    def __init__(self, events, refuse=lambda command: False):
        self.events = events
        self.refuse = refuse

    def validate_command(self, command, *, provider):
        self.events.append(("validate", tuple(command)))
        if self.refuse(command):
            raise ExecutableDependencyError("subject_mismatch", provider)


def fake_launch(events):
    def launch(command, **kwargs):
        events.append(("launch", tuple(command)))
        if "--output-last-message" in command:
            final = command[command.index("--output-last-message") + 1]
            with open(final, "w", encoding="utf-8") as handle:
                handle.write("synthetic final\n")
        return LaunchResult(command=command, returncode=0, output="")
    return launch


def bind_dependency(monkeypatch, dependency):
    monkeypatch.setattr(executable_dependency_startup, "current_dependency_for_provider",
                        lambda *_args, **_kwargs: dependency)
    # A bound dependency is admitted on review only (`_refuse_unwired_executor_spec`), and
    # the probe never runs on review; the refusal is lifted here so only S2's ordering
    # inside the execute path is under test.
    monkeypatch.setattr(launcher, "_refuse_unwired_executor_spec", lambda *_args: None)


def test_validate_runs_before_the_probe_and_last_before_launch(tmp_path, monkeypatch):
    events = []
    bind_dependency(monkeypatch, RecordingDependency(events))
    monkeypatch.setattr(launcher.sys, "platform", "linux")

    def probe(executable, *_args):
        events.append(("probe", executable))
        return True

    monkeypatch.setattr(launcher, "_codex_usage_version", probe)
    monkeypatch.setattr(launcher, "launch", fake_launch(events))
    launcher.launch_with_spec(codex_spec(tmp_path), codex_usage_capture=True)
    kinds = [event[0] for event in events]
    assert kinds.count("probe") == 1 and kinds[-1] == "launch"
    probe_at = kinds.index("probe")
    final_command = events[-1][1]
    assert events[probe_at - 1] == ("validate", final_command)
    assert events[-2] == ("validate", final_command)


def test_a_mismatched_binary_is_never_probed(tmp_path, monkeypatch):
    events = []
    # The final command (after every rewrite) names a different subject than admission saw.
    bind_dependency(monkeypatch, RecordingDependency(
        events, refuse=lambda command: "--output-last-message" in command))
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher, "_codex_usage_version",
                        lambda *_args: pytest.fail("a mismatched binary was probed"))
    monkeypatch.setattr(launcher, "launch", lambda *_a, **_k: pytest.fail("a mismatched binary was launched"))
    with pytest.raises(ExecutableDependencyError, match="subject_mismatch"):
        launcher.launch_with_spec(codex_spec(tmp_path), codex_usage_capture=True)
    assert not [event for event in events if event[0] != "validate"]


@pytest.mark.skipif(os.name != "posix", reason="the probe's process-group kill is POSIX")
def test_probe_is_an_owned_executor_trusted_launch_under_the_audit_hook(tmp_path, monkeypatch):
    # The suite-wide launch audit hook (conftest, fail=True) refuses a provider start
    # without the owned marker, so an unowned probe of an executable named `codex` raises.
    child = tmp_path / "codex"
    child.write_text("#!" + sys.executable + "\nprint('codex-cli 0.159.2')\n")
    child.chmod(0o700)
    roles, markers = [], []
    owned = panel_invoker.launch_owned

    def recording_owned(argv, *, role, profile, **kwargs):
        roles.append((list(argv), role))
        return owned(argv, role=role, profile=profile, **kwargs)

    real_popen = subprocess.Popen

    def recording_popen(argv, *args, **kwargs):
        if "--version" in list(argv):
            markers.append(panel_invoker._OWNED_LAUNCH.get(False))
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(panel_invoker, "launch_owned", recording_owned)
    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    env = launcher.child_executor_env({**os.environ})
    assert launcher._codex_usage_version(str(child), env, str(tmp_path), 5.0) is True
    assert roles == [([str(child), "--version"], panel_invoker.SeatLaunchRole.EXECUTOR_TRUSTED)]
    assert markers == [True]


@pytest.mark.skipif(os.name != "posix", reason="the review consume path is POSIX")
@pytest.mark.parametrize("observed", [False, True])
def test_a_seat_credential_line_is_redacted_before_every_sink(tmp_path, monkeypatch, capsys, observed):
    secret = "synthetic-seat-credential-0123456789"
    script = tmp_path / "child.py"
    script.write_text(f"print('LEAK {secret}', flush=True)\n")

    def fake_owned(argv, *, role, profile, supervisor=None, **kwargs):
        assert role is panel_invoker.SeatLaunchRole.PROVIDER_REVIEW
        return subprocess.Popen([sys.executable, str(script)], **kwargs)

    class Observer:
        def __init__(self):
            self.lines = []

        def observe(self, line):
            self.lines.append(line)

        def invalidate(self, reason):
            pass

    observer = Observer() if observed else None
    monkeypatch.setattr(panel_invoker, "launch_owned", fake_owned)
    token = panel_invoker._SEAT_REDACTIONS.set((secret,))
    log = tmp_path / "output.log"
    try:
        result = launcher.launch(["codex", "exec", "--json", "-"], action="review",
                                 _review_profile=object(), log_path=log, stream_output=True,
                                 cwd=str(tmp_path), _codex_usage_observer=observer)
    finally:
        panel_invoker._SEAT_REDACTIONS.reset(token)
    sinks = {"output": result.output, "log": log.read_text(encoding="utf-8"),
             "stream": capsys.readouterr().out}
    if observed:
        sinks["observer"] = "".join(observer.lines)
    for name, text in sinks.items():
        assert "LEAK" in text, name
        assert secret not in text, name


def test_native_windows_review_is_refused_before_any_spawn(monkeypatch):
    from phase_loop_runtime import sandbox_egress, windows_process

    def forbidden(*_args, **_kwargs):
        pytest.fail("a process or seat was started")

    monkeypatch.setattr(launcher, "_native_windows", lambda: True)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(windows_process, "run_owned", forbidden)
    monkeypatch.setattr(panel_invoker, "launch_owned", forbidden)
    monkeypatch.setattr(panel_invoker, "_await_gemini_login", forbidden)
    monkeypatch.setattr(sandbox_egress, "isolated_network", forbidden)
    monkeypatch.setattr(launcher, "_launch_windows_owned", forbidden)
    with pytest.raises(ValueError, match="review_unsupported_on_windows"):
        launcher.launch(["codex", "exec", "-"], action="review", ephemeral_monitor=True)


def test_native_windows_ephemeral_recursion_forwards_action_profile_and_usage(monkeypatch):
    calls = []
    original = launcher.launch

    def recording_launch(command, **kwargs):
        calls.append(kwargs)
        return original(command, **kwargs)

    def fake_windows_owned(command, **kwargs):
        return LaunchResult(command=command, returncode=0, output="ok")

    profile, observer = object(), object()
    monkeypatch.setattr(launcher, "_native_windows", lambda: True)
    monkeypatch.setattr(launcher, "launch", recording_launch)
    monkeypatch.setattr(launcher, "_launch_windows_owned", fake_windows_owned)
    result = original([sys.executable, "-c", "pass"], action="repair", _review_profile=profile,
                      ephemeral_monitor=True, _codex_usage_observer=observer, _launch_deadline=123.0)
    assert result.returncode == 0 and result.log_path is None
    assert len(calls) == 1
    inner = calls[0]
    assert inner["log_path"] is not None
    assert inner["action"] == "repair"
    assert inner["_review_profile"] is profile
    assert inner["_codex_usage_observer"] is observer
    assert inner["_launch_deadline"] == 123.0


def test_review_recursion_forwards_the_deadline_and_no_observer(monkeypatch):
    from phase_loop_runtime import sandbox_egress

    calls = []
    original = launcher.launch
    profile = object()

    @contextlib.contextmanager
    def seat_profile(command, **_kwargs):
        yield ["owned", *command], profile

    def recording_launch(command, **kwargs):
        calls.append((command, kwargs))
        return LaunchResult(command=command, returncode=0, output="")

    monkeypatch.setattr(launcher, "_native_windows", lambda: False)
    monkeypatch.setattr(panel_invoker, "_await_gemini_login", lambda *_args: None)
    monkeypatch.setattr(sandbox_egress, "isolated_network", lambda **_kwargs: contextlib.nullcontext(()))
    monkeypatch.setattr(panel_invoker, "_seat_command_profile", seat_profile)
    monkeypatch.setattr(launcher, "launch", recording_launch)
    original(["codex", "exec", "-"], action="review", _codex_usage_observer=object(),
             _launch_deadline=456.0)
    assert len(calls) == 1
    command, inner = calls[0]
    assert command[0] == "owned"
    assert inner["action"] == "review" and inner["_review_profile"] is profile
    assert inner["_launch_deadline"] == 456.0
    assert inner["_codex_usage_observer"] is None


def test_review_launch_starts_no_probe_and_records_disabled_capture(tmp_path, monkeypatch):
    events = []
    real_popen = subprocess.Popen
    owned = panel_invoker.launch_owned

    def refuse_version(argv):
        if "--version" in list(argv):
            pytest.fail("a usage probe started on a review launch")

    def guarded_owned(argv, *args, **kwargs):
        refuse_version(argv)
        return owned(argv, *args, **kwargs)

    def guarded_popen(argv, *args, **kwargs):
        refuse_version(argv)
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(panel_invoker, "launch_owned", guarded_owned)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    created = []
    collector = launcher._CodexUsageCollector
    monkeypatch.setattr(launcher, "_CodexUsageCollector", lambda: created.append(1) or collector())
    monkeypatch.setattr(launcher, "launch", fake_launch(events))
    spec = codex_spec(tmp_path, product_action="review")
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert [event[0] for event in events] == ["launch"]
    assert "--json" in events[0][1]
    assert created == []
    assert result.jevdrill_usage is None
    assert result.jevdrill_protocol_diagnostics == DISABLED
    # The same spec on execute does start the probe: the gate is the action, not the path.
    probes = []
    monkeypatch.setattr(launcher, "_codex_usage_version", lambda *_args: probes.append(1) or False)
    launcher.launch_with_spec(replace(spec, prompt_bundle=replace(spec.prompt_bundle, product_action="execute")),
                              codex_usage_capture=True)
    assert probes == [1]
