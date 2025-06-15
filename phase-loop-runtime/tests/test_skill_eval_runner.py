"""Offline runner tests and real Linux owned-process observer controls."""

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from phase_loop_runtime import launcher, panel_invoker, sandbox_egress, sandbox_policy
from phase_loop_runtime import skill_eval as ev, skill_eval_runner as runner
from phase_loop_runtime.skill_eval_access import AccessObserver


PILOT = Path(__file__).parent / "fixtures" / "skill_eval" / "pilot.json"
COMPLETE = '\n'.join([
    '{"type":"thread.started","thread_id":"opaque"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"answer","type":"agent_message","text":"Evidence plan."}}',
    '{"type":"turn.completed","usage":{"input_tokens":20,"output_tokens":3}}'])


@pytest.fixture(autouse=True)
def c_locale(monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")


@pytest.fixture
def experiment(tmp_path):
    root = tmp_path / "experiment"
    frozen = ev.prepare(PILOT, root)
    return root, frozen, ev.Spec.model_validate(frozen["spec"])


@pytest.mark.parametrize("code,stderr,allowed", [
    (0, "", False), (128, "fatal: not a git repository (or any parent): .git\n", True),
    (128, "fatal: detected dubious ownership", False), (1, "", False),
    (127, "git missing", False), (128, "not a git repository", False),
])
def test_git_tristate(monkeypatch, tmp_path, code, stderr, allowed):
    monkeypatch.setattr(runner.review_stage, "host_git", lambda *a, **k:
                        SimpleNamespace(returncode=code, stderr=stderr))
    if allowed:
        runner.require_non_git(tmp_path)
    else:
        with pytest.raises(ValueError):
            runner.require_non_git(tmp_path)


@pytest.mark.parametrize("error", [OSError("missing"), ValueError("unavailable"),
                                  subprocess.TimeoutExpired("git", 1)])
def test_git_unavailable_refused(monkeypatch, tmp_path, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(runner.review_stage, "host_git", fail)
    with pytest.raises(ValueError, match="unavailable"):
        runner.require_non_git(tmp_path)


def test_git_probe_requires_frozen_locale(monkeypatch, tmp_path):
    monkeypatch.setenv("LC_ALL", "fr_FR")
    with pytest.raises(ValueError, match="locale"):
        runner.require_non_git(tmp_path)


def test_real_in_git_stage_refused_before_watch(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    monkeypatch.setattr(runner, "AccessObserver", lambda *a: pytest.fail("watch started"))
    with pytest.raises(ValueError, match="inside Git"):
        with runner.staged(lambda p: [], {"ignored.txt": "important"}, tmp_path):
            pytest.fail("stage admitted")


def test_effective_command_and_features(experiment):
    _, frozen, spec = experiment
    command = runner.command_for(Path("/fixture"), spec, "NATURAL TASK")
    assert command[0] == spec.executable.path and command[-1] == "NATURAL TASK"
    for flag in ("--ephemeral", "--ignore-rules", "--strict-config", "--ignore-user-config",
                 "--skip-git-repo-check", "--json"):
        assert command.count(flag) == 1
    assert command[command.index("--sandbox") + 1] == "read-only"
    settings = [command[i+1] for i, value in enumerate(command[:-1]) if value == "-c"]
    assert 'web_search="disabled"' in settings
    for feature in panel_invoker._BROKER_CODEX_DISABLED_FEATURES:
        enabled = feature in panel_invoker._BROKER_CODEX_SANDBOX_ENABLED_FEATURES
        assert f"features.{feature}={str(enabled).lower()}" in settings
    assert not any("mcp_servers" in item for item in command)
    assert frozen["config"] == ev.protocol_config(spec)


@pytest.mark.parametrize("output", [
    "", '{"type":"turn.started"}', '{"type":"turn.failed","error":{"message":"failed"}}',
    '{"type":"turn.completed"}', COMPLETE + '\ntruncated',
    COMPLETE + '\n{"type":"future.event"}',
    COMPLETE.replace('"agent_message"', '"unknown_tool"'),
    COMPLETE.replace('"Evidence plan."', '""'),
    'unexpected warning\n' + COMPLETE,
    COMPLETE.replace('"turn.started"', '"unknown.event"'),
    COMPLETE.replace('"turn.completed","usage"', '"turn.failed","usage"'),
    '[]\n' + COMPLETE,
])
def test_incomplete_failed_or_mixed_stream_refused(output):
    with pytest.raises(ValueError):
        runner.parse_stream(output, [])


def test_complete_event_stream_and_exact_diagnostics():
    text, usage = runner.parse_stream(COMPLETE, [])
    assert text == "Evidence plan." and usage["output_tokens"] == 3
    assert runner.parse_stream("pinned diagnostic\n" + COMPLETE, ["pinned diagnostic"])[0] == text
    with pytest.raises(ValueError):
        runner.parse_stream("pinned diagnostic with extra bytes\n" + COMPLETE, ["pinned diagnostic"])


@pytest.mark.parametrize("events", [
    ["message", "start", "complete"],
    ["start", "message", "start", "complete"],
    ["start", "complete", "message"],
    ["start", "message", "complete", "message"],
    ["message", "complete"],
])
def test_single_turn_ordering_refuses_stale_or_late_messages(events):
    records = {
        "start": {"type": "turn.started"},
        "message": {"type": "item.completed", "item": {
            "id": "answer", "type": "agent_message", "text": "plan"}},
        "complete": {"type": "turn.completed"},
    }
    with pytest.raises(ValueError):
        runner.parse_stream("\n".join(json.dumps(records[e]) for e in events), [])


def test_single_turn_allows_tool_read_lifecycle_and_final_message():
    events = [{"type": "thread.started", "thread_id": "opaque"}, {"type": "turn.started"}]
    for kind in ("item.started", "item.updated", "item.completed"):
        events.append({"type": kind, "item": {
            "id": "read", "type": "command_execution", "command": "cat input.txt",
            "aggregated_output": "fixture facts" if kind == "item.completed" else "",
            "status": "completed" if kind == "item.completed" else "in_progress"}})
    events.extend(json.loads(line) for line in COMPLETE.splitlines()[2:])
    assert runner.parse_stream("\n".join(map(json.dumps, events)), []) == (
        "Evidence plan.", {"input_tokens": 20, "output_tokens": 3})


@pytest.mark.skipif(sys.platform != "linux", reason="Linux inotify")
@pytest.mark.parametrize("behavior", ["read", "open", "self_report", "none"])
def test_real_owned_boundary_observes_only_final_copy(tmp_path, behavior):
    files = {"input.txt": "fixture payload", "ignored.txt": "still a fixture",
             ".guidance/plan.md": "guide payload", "AGENTS.md": ev.ROUTE}
    parent = sandbox_policy.staging_root()
    spec = ev.Spec.model_validate(ev.load(PILOT))
    try:
        with runner.staged(lambda p: runner.command_for(p, spec, "task"), files, parent) as (cmd, root, preimage):
            assert root != preimage
            assert cmd[cmd.index("--cd") + 1] == str(root)
            assert not (root / ".git").exists()
            source = (
                "import os,json\n"
                + ("[open(p).read() for p in ['input.txt','ignored.txt','.guidance/plan.md']]\n"
                   if behavior == "read" else
                   "f=open('input.txt');f.close()\n" if behavior == "open" else
                   "print('I read input.txt and .guidance/plan.md')\n"
                   if behavior == "self_report" else "pass\n")
                + "print(json.dumps({'home':os.environ['HOME'],'canary':os.path.exists(" +
                repr(str(tmp_path / "operator.txt")) + ")}))")
            (tmp_path / "operator.txt").write_text("outside declared inputs")
            process_command = ["/usr/bin/python3", "-I", "-S", "-c", source]
            with ExitStack() as stack:
                prefix = stack.enter_context(sandbox_egress.isolated_network(required=True, timeout_s=None))
                token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
                stack.callback(panel_invoker._EGRESS_LAUNCH_PREFIX.reset, token)
                owned, profile = stack.enter_context(panel_invoker._seat_command_profile(
                    process_command, env=os.environ, cwd=root, readonly_paths=(root,)))
                runner.verify_tree(root, files)
                # Source watch proves the launcher/profile do not read the preimage.
                source_observer = AccessObserver(preimage, list(files))
                observed = AccessObserver(root, list(files))
                with source_observer, observed:
                    result = launcher.launch(owned, action="review", _review_profile=profile,
                                             cwd=root, env=dict(profile.env), ephemeral_monitor=True)
                assert result.returncode == 0, result.output
                facts = json.loads(result.output.splitlines()[-1])
                assert not facts["canary"]
                assert facts["home"] != str(Path.home())
                assert not source_observer.errors and not observed.errors
                assert not any(row["access"] for row in source_observer.events.values())
                assert observed.events["input.txt"]["open"] == (behavior in {"read", "open"})
                assert observed.events["input.txt"]["access"] == (behavior == "read")
                assert observed.events["ignored.txt"]["access"] == (behavior == "read")
                assert observed.events[ev.GUIDE]["access"] == (behavior == "read")
                runner.verify_tree(root, files)
    except sandbox_egress.EgressUnavailable:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            raise
        pytest.skip("kernel seat-owner support unavailable")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux inotify")
@pytest.mark.parametrize("mutation", ["write", "replace", "overflow", "watch_loss"])
def test_observer_invalidates_mutation_overflow_and_watch_loss(tmp_path, mutation):
    path = tmp_path / "fixture"
    path.write_text("original")
    observer = AccessObserver(tmp_path, ["fixture"])
    with observer:
        if mutation == "write":
            path.write_text("changed")
        elif mutation == "replace":
            replacement = tmp_path / "replacement"
            replacement.write_text("replacement")
            replacement.replace(path)
        else:
            observer.feed(struct.pack("iIII", -1, 0x4000 if mutation == "overflow" else 0x8000, 0, 0))
    assert observer.errors


@pytest.mark.skipif(sys.platform != "linux", reason="Linux inotify")
def test_observer_closes_descriptor_when_watch_initialization_fails(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from phase_loop_runtime import skill_eval_access
    (tmp_path / "fixture").write_text("fixture")
    fd = os.open(tmp_path / "fixture", os.O_RDONLY)
    libc = SimpleNamespace(inotify_init1=Mock(return_value=fd),
                           inotify_add_watch=Mock(return_value=-1))
    monkeypatch.setattr(skill_eval_access.ctypes, "CDLL", lambda *a, **k: libc)
    with pytest.raises(OSError, match="inotify_add_watch"):
        AccessObserver(tmp_path, ["fixture"])
    with pytest.raises(OSError):
        os.fstat(fd)


def test_tree_integrity_links_and_hash_drift(tmp_path):
    files = {"fixture": "original"}
    (tmp_path / "fixture").write_text("original")
    runner.verify_tree(tmp_path, files)
    (tmp_path / "fixture").write_text("changed")
    with pytest.raises(ValueError, match="integrity"):
        runner.verify_tree(tmp_path, files)
    (tmp_path / "linked").symlink_to(tmp_path / "fixture")
    with pytest.raises(ValueError, match="link"):
        runner.verify_tree(tmp_path, files)


def test_unresolved_placeholder_refused_before_profile(experiment, monkeypatch):
    root, frozen, spec = experiment
    monkeypatch.setattr(launcher, "_resolve_review_stage", lambda cmd, *a, **k: cmd)
    with pytest.raises(ValueError, match="placeholder"):
        with runner.staged(lambda p: runner.command_for(p, spec, "task"),
                           {"fixture": "payload"}, sandbox_policy.staging_root()):
            pytest.fail("placeholder admitted")


def test_pinned_executable_changed_or_linked_refused(experiment, tmp_path, monkeypatch):
    _, _, spec = experiment
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nprintf 'codex-cli test\\n'\n")
    executable.chmod(0o700)
    spec.executable.path = str(executable)
    spec.executable.sha256 = ev.digest(executable.read_bytes())
    spec.executable.version = "codex-cli test"
    calls = []
    def metadata(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="codex-cli test\n", stderr="")
    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", metadata)
    runner.verify_executable(spec)
    assert calls[0][0] == [str(executable), "--version"]
    assert calls[0][1]["deadline_s"] == panel_invoker._CODEX_SANDBOX_PROBE_TIMEOUT_S
    executable.write_text("#!/bin/sh\nexit 1\n")
    with pytest.raises(ValueError, match="identity"):
        runner.verify_executable(spec)
    linked = tmp_path / "linked"
    linked.symlink_to(executable)
    spec.executable.path = str(linked)
    with pytest.raises(ValueError, match="linked"):
        runner.verify_executable(spec)


def test_executable_wrapper_identity_cannot_substitute_native(experiment, tmp_path, monkeypatch):
    _, _, spec = experiment
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    spec.executable.path = str(executable)
    spec.executable.sha256 = ev.digest(executable.read_bytes())
    monkeypatch.setattr(panel_invoker, "_seat_provider_source", lambda *a: ("codex", "/different/codex"))
    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness",
                        lambda *a, **k: pytest.fail("metadata/model launch"))
    with pytest.raises(ValueError, match="native"):
        runner.verify_executable(spec)


@pytest.fixture
def fake_boundary(monkeypatch):
    @contextmanager
    def network(**kwargs):
        yield ("fake-held-network",)
    @contextmanager
    def profile(cmd, **kwargs):
        yield cmd, SimpleNamespace(env={"HOME": "/fresh-seat", "LC_ALL": "C"})
    monkeypatch.setattr(runner, "verify_executable", lambda spec: None)
    monkeypatch.setattr(sandbox_egress, "isolated_network", network)
    monkeypatch.setattr(panel_invoker, "_seat_command_profile", profile)
    return monkeypatch


@pytest.mark.parametrize("failure", ["diagnostic", "unknown", "unsupported", "timeout", "unavailable"])
def test_probe_failure_refuses_subject_and_binds_terminal(experiment, fake_boundary, failure):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    ev.write_new(root / "trials" / trial["id"] / "started.json", ev.binding(frozen, spec, trial))
    def fail(*args):
        raise ValueError("seat_tool_sandbox_unavailable" if failure == "diagnostic" else failure)
    fake_boundary.setattr(runner, "probe_sandbox", fail)
    fake_boundary.setattr(launcher, "launch", lambda *a, **k: pytest.fail("subject called"))
    fake_boundary.setattr(runner, "AccessObserver", lambda *a: pytest.fail("observation started"))
    runner.run_trial(root, frozen, spec, trial)
    directory = root / "trials" / trial["id"]
    terminal = ev.load(directory / "terminal.json")
    assert terminal["status"] == "invalid"
    assert terminal["binding"] == ev.binding(frozen, spec, trial)
    launch = ev.load(directory / "launch.json")
    assert launch["interrupted"] is None and launch["cleanup_evidence"] is None
    assert not ev.evidence(root, frozen, spec, trial)["valid"]


@pytest.mark.parametrize("mode", ["success", "exit_failure", "diagnostic", "timeout", "interrupt"])
def test_probe_same_owned_profile_and_process_cleanup(tmp_path, monkeypatch, mode):
    captured = []
    profile = SimpleNamespace(env={"LC_ALL": "C"})
    command = ["codex", "exec", "--cd", str(tmp_path), "--sandbox", "read-only", "task"]
    def popen(argv, **kwargs):
        captured.append((argv, kwargs))
        assert kwargs.pop("profile") is profile
        assert kwargs.pop("role") == panel_invoker.SeatLaunchRole.PROVIDER_REVIEW
        source = ("import time;time.sleep(30)" if mode in {"timeout", "interrupt"} else
                  "import sys;print('bwrap: synthetic refusal',file=sys.stderr);sys.exit(1)"
                  if mode == "diagnostic" else "raise SystemExit(7)" if mode == "exit_failure" else "pass")
        proc = subprocess.Popen(["/usr/bin/python3", "-I", "-S", "-c", source], **kwargs)
        captured.append(proc)
        return proc
    monkeypatch.setattr(panel_invoker, "launch_owned", popen)
    monkeypatch.setattr(panel_invoker, "_CODEX_SANDBOX_PROBE_TIMEOUT_S", .05)
    if mode == "interrupt":
        original = panel_invoker._anchor_process_group
        def interrupt(proc):
            original(proc)
            raise KeyboardInterrupt()
        monkeypatch.setattr(panel_invoker, "_anchor_process_group", interrupt)
    if mode == "success":
        runner.probe_sandbox(command, ["/owned/codex"], profile, tmp_path)
    else:
        error = (subprocess.TimeoutExpired if mode == "timeout" else
                 KeyboardInterrupt if mode == "interrupt" else ValueError)
        with pytest.raises(error):
            runner.probe_sandbox(command, ["/owned/codex"], profile, tmp_path)
    assert captured[0][0][0] == "/owned/codex"
    assert captured[0][1]["cwd"] == str(tmp_path)
    assert captured[0][1]["start_new_session"] is True
    assert captured[1].poll() is not None
    assert not panel_invoker._process_group_exists(captured[1].pid)


@pytest.mark.parametrize("failure", [False, True, "interrupt", "system_exit"])
def test_trial_observation_envelope_and_terminal_failure(experiment, fake_boundary, failure):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    ev.write_new(root / "trials" / trial["id"] / "started.json", ev.binding(frozen, spec, trial))
    fake_boundary.setattr(runner, "probe_sandbox", lambda *a: None)
    seen = []
    def subject(argv, **kwargs):
        seen.append(kwargs)
        assert kwargs["action"] == "review" and kwargs["ephemeral_monitor"]
        assert "timeout_seconds" not in kwargs
        assert argv[-1].startswith(ev.ENVELOPE)
        assert not any(launcher.CODEX_REVIEW_STAGE_PREFIX in arg for arg in argv)
        if failure == "interrupt":
            raise KeyboardInterrupt()
        if failure == "system_exit":
            raise SystemExit(2)
        for path in kwargs["cwd"].rglob("*"):
            if path.is_file():
                path.read_bytes()
        return launcher.LaunchResult(command=argv, returncode=1 if failure else 0,
                                     output=COMPLETE)
    fake_boundary.setattr(launcher, "launch", subject)
    if failure in {"interrupt", "system_exit"}:
        with pytest.raises(KeyboardInterrupt if failure == "interrupt" else SystemExit):
            runner.run_trial(root, frozen, spec, trial)
    else:
        runner.run_trial(root, frozen, spec, trial)
    evidence = ev.evidence(root, frozen, spec, trial)
    assert evidence["valid"] == (not failure)
    assert len(seen) == 1 and not seen[0]["cwd"].exists()
    terminal = ev.load(root / "trials" / trial["id"] / "terminal.json")
    assert terminal["status"] == ("invalid" if failure else "completed")
    launch = ev.load(root / "trials" / trial["id"] / "launch.json")
    assert launch["cleanup_evidence"] is None
    assert terminal["interrupted"] == (failure in {"interrupt", "system_exit"})


@pytest.mark.parametrize("returncode,transcript,cleanup", [
    (-2, "", {"reason": "interrupt", "cleanup_scope": "process_group",
              "signals_sent": ["SIGTERM"], "result": "terminated",
              "final_returncode": -2, "process_alive_after_cleanup": False}),
    (-2, '{"type":"turn.started"}', {"reason": "interrupt", "cleanup_scope": "process_group",
                                      "signals_sent": ["SIGTERM", "SIGKILL"],
                                      "result": "cleanup_failed", "final_returncode": None,
                                      "process_alive_after_cleanup": True}),
    (0, COMPLETE, {"reason": "interrupt", "cleanup_scope": "process_group",
                   "signals_sent": [], "result": "already_exited",
                   "final_returncode": 0, "process_alive_after_cleanup": False}),
    (0, COMPLETE, None),
])
def test_returned_interrupt_retains_bound_evidence(
        experiment, fake_boundary, returncode, transcript, cleanup):
    root, frozen, spec = experiment
    trial = frozen["schedule"][0]
    directory = root / "trials" / trial["id"]
    bound = ev.binding(frozen, spec, trial)
    ev.write_new(directory / "started.json", bound)
    fake_boundary.setattr(runner, "probe_sandbox", lambda *a: None)
    stages = []
    def subject(argv, **kwargs):
        stages.append(kwargs["cwd"])
        for path in kwargs["cwd"].rglob("*"):
            if path.is_file():
                path.read_bytes()
        return launcher.LaunchResult(
            command=argv, returncode=returncode, output=transcript,
            interrupted=True, timed_out=False, stalled=False, cleanup_evidence=cleanup)
    fake_boundary.setattr(launcher, "launch", subject)
    with pytest.raises(KeyboardInterrupt):
        runner.run_trial(root, frozen, spec, trial)
    terminal = ev.load(directory / "terminal.json")
    launch = ev.load(directory / "launch.json")
    access = ev.load(directory / "access.json")
    assert terminal["binding"] == bound
    assert terminal["status"] == "invalid" and terminal["reason"] == "KeyboardInterrupt"
    assert terminal["interrupted"] is True and terminal["output"] == ""
    assert launch["binding"] == access["binding"] == {
        **bound, "output_digest": ev.digest(b"")}
    assert launch["interrupted"] is True and launch["cleanup_evidence"] == cleanup
    assert launch["returncode"] == returncode and launch["stream_valid"] is False
    assert launch["usage"] is None
    assert terminal["launch_digest"] == ev.digest(launch)
    assert terminal["access_digest"] == ev.digest(access)
    assert (directory / "transcript.txt").read_text() == transcript
    assert launch["transcript_digest"] == ev.digest(transcript.encode())
    assert not ev.evidence(root, frozen, spec, trial)["valid"]
    assert len(stages) == 1 and not stages[0].exists()


def test_run_stops_before_next_claim_on_returned_interrupt(experiment, fake_boundary):
    root, frozen, spec = experiment
    assert len(frozen["schedule"]) >= 2
    fake_boundary.setattr(runner, "probe_sandbox", lambda *a: None)
    calls = []
    def subject(argv, **kwargs):
        calls.append(kwargs["cwd"])
        return launcher.LaunchResult(
            command=argv, returncode=-2, output="", interrupted=True,
            cleanup_evidence={"reason": "interrupt", "cleanup_scope": "process_group",
                              "signals_sent": ["SIGTERM"], "result": "terminated",
                              "final_returncode": -2, "process_alive_after_cleanup": False})
    fake_boundary.setattr(launcher, "launch", subject)
    cancelled = False
    try:
        ev.run(root)
    except KeyboardInterrupt:
        cancelled = True
    assert len(calls) == 1
    assert cancelled
    first = root / "trials" / frozen["schedule"][0]["id"]
    retained = {name: (first / name).read_bytes() for name in (
        "started.json", "terminal.json", "launch.json", "access.json", "transcript.txt")}
    terminal = ev.load(first / "terminal.json")
    assert terminal["status"] == "invalid" and terminal["interrupted"] is True
    assert not ev.evidence(root, frozen, spec, frozen["schedule"][0])["valid"]
    for trial in frozen["schedule"][1:]:
        directory = root / "trials" / trial["id"]
        assert not (directory / "started.json").exists()
        assert not (directory / "terminal.json").exists()
    # A later explicit run skips the cancelled claim and can claim only untouched work.
    with pytest.raises(KeyboardInterrupt):
        ev.run(root)
    assert len(calls) == 2
    assert all((first / name).read_bytes() == raw for name, raw in retained.items())
    second = root / "trials" / frozen["schedule"][1]["id"]
    assert (second / "started.json").is_file()
    assert ev.load(second / "terminal.json")["interrupted"] is True
    assert not (root / "trials" / frozen["schedule"][2]["id"] / "started.json").exists()
