"""Executor review uses the same owner, including supervised launches."""

import json
import os
import sys

import pytest

from phase_loop_runtime import launcher, sandbox_egress


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned executor review")


class _Lease:
    generation = "seat-executor-review"

    def __init__(self, descriptor):
        self.descriptor = descriptor

    def fileno(self):
        return self.descriptor


@pytest.mark.parametrize("supervised", [False, True])
def test_executor_review_has_private_view_and_no_lease_descriptor(tmp_path, supervised):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("declared review input")
    canary = tmp_path / "operator-input.txt"
    canary.write_text("undeclared input")
    descriptor = os.open(tmp_path / "lease", os.O_RDWR | os.O_CREAT, 0o600)
    source = """
import json,os,sys
with open('/proc/self/status') as stream:
 status=dict(line.split(':',1) for line in stream if ':' in line)
open_descriptors=[]
for descriptor in range(3,256):
 try: os.fstat(descriptor)
 except OSError: continue
 open_descriptors.append(descriptor)
print(json.dumps({'namespace':os.stat('/proc/self/ns/pid').st_ino,
 'bounding':status['CapBnd'].strip(),'no_new_privs':status['NoNewPrivs'].strip(),
 'ambient':os.getenv('SYNTHETIC_OPERATOR_VALUE'),'canary':os.path.exists(sys.argv[1]),
 'input':open('input.txt').read(),'open_descriptors':open_descriptors}))
"""
    try:
        try:
            result = launcher.launch(
                ["/usr/bin/python3", "-I", "-S", "-c", source, str(canary)],
                action="review", cwd=workspace, log_path=tmp_path / "review.log",
                env={"PATH": "/usr/bin:/bin", "SYNTHETIC_OPERATOR_VALUE": "operator-value"},
                lease_authority=_Lease(descriptor) if supervised else None,
            )
        except sandbox_egress.EgressUnavailable:
            if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
                raise
            pytest.skip("kernel seat-owner support unavailable")
    finally:
        os.close(descriptor)
    assert result.returncode == 0, result.output
    facts = json.loads(result.output)
    assert facts["namespace"] != os.stat("/proc/self/ns/pid").st_ino
    assert facts["bounding"] == "0000000000000000"
    assert facts["no_new_privs"] == "1"
    assert facts["ambient"] is None
    assert facts["canary"] is False
    assert facts["input"] == "declared review input"
    assert facts["open_descriptors"] == []
    assert not result.stalled and not result.timed_out
    if supervised:
        assert result.supervisor_receipt["process_tree_empty"] is True


def test_trusted_executor_keeps_operator_environment(tmp_path):
    result = launcher.launch(
        ["/usr/bin/python3", "-I", "-S", "-c", "import os;print(os.getenv('SYNTHETIC_OPERATOR_VALUE'))"],
        env={"PATH": "/usr/bin:/bin", "SYNTHETIC_OPERATOR_VALUE": "operator-value"}, cwd=tmp_path,
    )
    assert result.returncode == 0
    assert result.output.strip() == "operator-value"


def test_executor_review_receives_its_declared_context_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = tmp_path / "context.md"
    context.write_text("declared context")
    source = "import pathlib,sys;print(pathlib.Path(sys.argv[sys.argv.index('--prompt-file')+1]).read_text())"
    try:
        result = launcher.launch(
            ["/usr/bin/python3", "-I", "-S", "-c", source, "--prompt-file", str(context)],
            action="review", cwd=workspace,
        )
    except sandbox_egress.EgressUnavailable:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            raise
        pytest.skip("kernel seat-owner support unavailable")
    assert result.returncode == 0, result.output
    assert result.output.strip() == "declared context"


def test_executor_review_does_not_terminate_for_quiet_observations(tmp_path, monkeypatch):
    original = launcher.run_heartbeat_summary

    def quiet_summary(**kwargs):
        summary = original(**kwargs)
        summary.update(stalled_suspect=True, quiet_level="blocked")
        return summary

    monkeypatch.setattr(launcher, "run_heartbeat_summary", quiet_summary)
    try:
        result = launcher.launch(
            ["/usr/bin/python3", "-I", "-S", "-c", "import time;time.sleep(2);print('completed')"],
            action="review", cwd=tmp_path, timeout_seconds=0.01, heartbeat_interval_seconds=0,
        )
    except sandbox_egress.EgressUnavailable:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            raise
        pytest.skip("kernel seat-owner support unavailable")
    assert result.returncode == 0, result.output
    assert result.output.strip() == "completed"
    assert not result.stalled and not result.timed_out


def test_unobserved_trusted_executor_uses_the_common_launch_marker(tmp_path, monkeypatch):
    import subprocess
    from phase_loop_runtime import panel_invoker
    original = subprocess.Popen
    seen = []

    def launch_process(argv, **kwargs):
        if argv[0] == "/bin/echo":
            seen.append(panel_invoker._OWNED_LAUNCH.get())
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', launch_process)
    result = launcher.launch(['/bin/echo', 'executor-output'], cwd=tmp_path)
    assert result.returncode == 0 and result.output.strip() == 'executor-output'
    assert seen == [True]


@pytest.mark.parametrize('failure', [ValueError, KeyboardInterrupt])
def test_convergence_review_closes_profile_and_context_on_launch_exception(tmp_path, monkeypatch, failure):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker
    from phase_loop_runtime.convergence.adapters import base

    closed = []
    previous = panel_invoker._EGRESS_LAUNCH_PREFIX.get()

    @contextmanager
    def network(**kwargs):
        try:
            yield ('synthetic-held-network',)
        finally:
            closed.append('network')

    @contextmanager
    def profile(command, **kwargs):
        try:
            yield command, panel_invoker.SeatProfile(env={})
        finally:
            closed.append('profile')

    def launch(*args, **kwargs):
        raise failure('synthetic launch interruption')

    monkeypatch.setattr(sandbox_egress, 'isolated_network', network)
    monkeypatch.setattr(panel_invoker, '_seat_command_profile', profile)
    monkeypatch.setattr(panel_invoker, 'launch_owned', launch)
    request = SimpleNamespace(argv=('codex',), cwd=tmp_path, allowed_action='review',
                              attempt_id='owned-review-cleanup', timeout_seconds=10)
    try:
        with pytest.raises(failure) as captured:
            base.run_bounded(request, provider='codex')
        assert captured.value.args == ('synthetic launch interruption',)
        assert closed == ['profile', 'network']
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == previous
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.set(previous)


@pytest.mark.parametrize('kind', ['hardlink', 'oversized'])
def test_executor_review_final_message_refuses_unsupported_output(tmp_path, monkeypatch, kind):
    from phase_loop_runtime.models import PromptBundle, InjectionMetadata
    from phase_loop_runtime.agy_canary_evidence import AgyCanaryEvidenceError

    bundle = PromptBundle('review', 'synthetic review', 'inline', product_action='review')
    spec = launcher.LaunchSpec(
        executor='codex', command=['codex', 'exec', 'synthetic review'], prompt_bundle=bundle,
        injection_metadata=InjectionMetadata('codex', 'inline'), delivery_mode='inline',
        dispatch_decision=None, available=True,
    )

    def complete(command, **kwargs):
        path = command[command.index('--output-last-message') + 1]
        if kind == 'hardlink':
            canary = tmp_path / 'synthetic-host-input'
            canary.write_text('synthetic unrelated input')
            os.link(canary, path)
        else:
            with open(path, 'wb') as stream:
                stream.truncate(32 * 1024 * 1024 + 1)
        return launcher.LaunchResult(command=command, returncode=0)

    monkeypatch.setattr(launcher, 'launch', complete)
    with pytest.raises(AgyCanaryEvidenceError):
        launcher.launch_with_spec(spec, log_path=tmp_path / 'run.log')


def test_convergence_review_waits_for_completion_without_a_model_deadline(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime.convergence.adapters import base
    from phase_loop_runtime.train_ledger import ConvergenceResultStatus

    request = SimpleNamespace(
        argv=('/usr/bin/python3', '-I', '-S', '-c',
              'import time;time.sleep(.3);print(\'{"status":"completed"}\')'),
        cwd=tmp_path, allowed_action='review', attempt_id='review-completion', timeout_seconds=.01,
    )
    result = base.run_bounded(request, provider='python3')
    assert result.status == ConvergenceResultStatus.COMPLETED
