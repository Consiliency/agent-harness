"""The prefix must reach the ACTUAL process, observed by its side effect.

Board round 10, codex, BLOCKING. The test that was being called the end-to-end proof --
`test_END_TO_END_the_prefix_reaches_adapter_invoke_through_the_real_broker` -- supplies an
adapter whose `invoke()` only READS the ContextVar::

    def invoke():
        seen["serve"] = _EGRESS_LAUNCH_PREFIX.get()   # "where the provider is launched"
        return ("OK", "probe-response")

It never calls `launch_provider`, `run_provider`, `_exec_leg`, or any launch seam. It
proves CONTEXT PROPAGATION through the broker, which is a real and necessary property, and
it was described -- by me, in its own docstring -- as proving the launch carries the prefix.
That is the proxy pattern in the artefact I had nominated as the proof.

codex's bypass, which defeats both instruments at once::

    def _popen():
        launch_provider = vars(subprocess)["Popen"]   # walker cannot resolve a subscript
        return launch_provider(cmd, ...)              # spelling still reads as the interface

The walker keeps passing (61 green), both helpers keep passing their direct tests, and the
broker test keeps reading its populated ContextVar -- while that production launch omits
the prefix entirely.

So this file does not inspect source, count call sites, or read a context variable. It
drives the REAL launch path with a prefix that has an OBSERVABLE SIDE EFFECT, and asserts
the side effect happened. A launch that skips the prefix cannot produce the marker,
however the skip is spelled.
"""

from __future__ import annotations

import os
from pathlib import Path
from contextlib import contextmanager

import pytest
from phase_loop_runtime import sandbox_egress


from phase_loop_runtime import panel_invoker


def _marker_prefix(marker: Path) -> tuple[str, ...]:
    """A prefix that RUNS: it writes `marker` with its own PID, then execs what follows.

    Chosen over a recording shim deliberately. Anything that merely records an argv is
    another proxy -- it proves what was passed to a function, not what a kernel executed.
    The marker exists only if this wrapper actually ran in front of the real command.

    The PID binds the two observations into one process: `exec` keeps the PID, so a payload
    that reports the same PID ran IN the prefixed process. A launch that prefixed some
    auxiliary command and started the provider separately would produce a marker and a
    payload with different PIDs (board PR #904 round 1, codex).
    """
    return ("/bin/sh", "-c", f'echo FIRED $$ > {marker}; exec "$@"', "--")


def _marker_pid(marker: Path) -> str:
    fired, pid = marker.read_text(encoding="utf-8").split()
    assert fired == "FIRED"
    return pid


@contextmanager
def _filtered_marker(marker, monkeypatch, *, administrative=False):
    original = panel_invoker.launch_provider
    if administrative:
        # Administrative calls build a private owner independently of review egress.
        # Observe that owner's prefix with the same executed PID witness.
        original_composer = panel_invoker._compose_launch_prefix

        def marked_prefix(cwd, process_owner=(), retain_caps=()):
            prefix = original_composer(cwd, process_owner, retain_caps)
            if process_owner and not panel_invoker._EGRESS_LAUNCH_PREFIX.get():
                return [*_marker_prefix(marker), *prefix]
            return prefix

        monkeypatch.setattr(panel_invoker, "_compose_launch_prefix", marked_prefix)
    processes = []

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        if _marker_prefix(marker)[2] in process.args:
            processes.append(process)
        return process

    monkeypatch.setattr(panel_invoker, "launch_provider", launch)
    with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set((*prefix, *_marker_prefix(marker)))
        try:
            yield processes
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)


def _assert_process_marker(marker, processes):
    assert len(processes) == 1
    assert _marker_pid(marker) == str(processes[0].pid)


class TestTheCLILegLaunch:
    def test_the_prefix_actually_executes_in_front_of_the_provider(self, tmp_path, monkeypatch):
        marker = tmp_path / "PREFIX_RAN"
        with _filtered_marker(marker, monkeypatch) as processes:
            run = panel_invoker._run_leg_with_liveness(
                ["/bin/sh", "-c", "echo provider-output"],
                cwd=tmp_path, env=dict(os.environ), deadline_s=60.0,
            )
        _assert_process_marker(marker, processes)
        assert run.returncode == 0, run.stderr
        assert "provider-output" in run.stdout

    def test_no_prefix_refuses_without_starting_a_provider(self, tmp_path, monkeypatch):
        monkeypatch.setattr(panel_invoker, "launch_provider", lambda *a, **k: pytest.fail("provider started"))
        with pytest.raises(sandbox_egress.EgressUnavailable, match="seat_filtered_egress_unavailable"):
            panel_invoker._run_leg_with_liveness(
                ["/bin/echo", "provider-output"], cwd=tmp_path,
                env=dict(os.environ), deadline_s=60.0,
            )


class TestTheHelpersThemselves:
    def test_launch_provider_executes_the_prefix(self, tmp_path):
        import subprocess
        marker = tmp_path / "LP_RAN"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            proc = panel_invoker.launch_provider(
                ["/bin/sh", "-c", "echo helper-output pid=$$"],
                stdout=subprocess.PIPE, cwd=str(tmp_path),
            )
            out = proc.communicate(timeout=60)[0].decode()
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        assert f"helper-output pid={_marker_pid(marker)}" in out
        assert proc.returncode == 0

    def test_run_provider_executes_the_administrative_owner_prefix(self, tmp_path, monkeypatch):
        marker = tmp_path / "RP_RAN"
        with _filtered_marker(marker, monkeypatch, administrative=True) as processes:
            done = panel_invoker.run_provider(
                ["/bin/echo", "hi"], capture_output=True, text=True,
                cwd=str(tmp_path), timeout=60,
            )
        _assert_process_marker(marker, processes)
        assert done.returncode == 0 and done.stdout.strip() == "hi"


class TestTheTUILaunch:
    @staticmethod
    def _provider(output_file):
        return ["/bin/sh", "-c", f"printf 'Reviewed.\\n\\nAGREE\\n' > {output_file}; exit 0"]

    def test_the_prefix_actually_executes_in_front_of_the_tui_provider(self, tmp_path, monkeypatch):
        marker = tmp_path / "TUI_PREFIX_RAN"
        output_file = tmp_path / "panel-claude.txt"
        with _filtered_marker(marker, monkeypatch) as processes:
            rc, text, status, tail = panel_invoker._run_claude_tui_session(
                command=self._provider(output_file), cwd=tmp_path, prompt="review this",
                output_file=output_file, timeout_s=60,
                env={"PATH": "/usr/bin:/bin"}, backstop_s=60,
            )
        _assert_process_marker(marker, processes)
        assert rc == 0 and status == "claude_tui_file_output", (status, tail)
        assert "AGREE" in text

    def test_no_prefix_refuses_on_the_tui_seam(self, tmp_path, monkeypatch):
        monkeypatch.setattr(panel_invoker, "launch_provider", lambda *a, **k: pytest.fail("provider started"))
        output_file = tmp_path / "panel-claude.txt"
        with pytest.raises(sandbox_egress.EgressUnavailable, match="seat_filtered_egress_unavailable"):
            panel_invoker._run_claude_tui_session(
                command=self._provider(output_file), cwd=tmp_path, prompt="review this",
                output_file=output_file, timeout_s=60,
                env={"PATH": "/usr/bin:/bin"}, backstop_s=60,
            )


class TestTheAgentViewLaunch:
    @pytest.mark.parametrize("prefixed", [False, True])
    def test_agent_view_refuses_without_launching(self, tmp_path, monkeypatch, prefixed):
        monkeypatch.setattr(panel_invoker, "launch_provider", lambda *a, **k: pytest.fail("provider started"))
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(tmp_path / "AGENT_VIEW") if prefixed else ())
        try:
            result = panel_invoker._exec_claude_agent_view_attempt(
                None, review_dir=tmp_path, timeout_s=60, prompt="p", env={},
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        assert result == ("UNAVAILABLE", "claude_agent_view_review_unsupported")
        assert not (tmp_path / "AGENT_VIEW").exists()


def test_owned_launch_executes_the_prefix_in_front_of_the_payload(tmp_path):
    import subprocess
    import pytest
    from phase_loop_runtime import sandbox_egress

    if not hasattr(os, "memfd_create"):
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks memfd support")
        pytest.skip("interpreter lacks memfd support")
    marker = tmp_path / "OWNED_PREFIX_RAN"
    try:
        with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set((*prefix, *_marker_prefix(marker)))
            try:
                proc = panel_invoker.launch_owned(
                    ["/bin/sh", "-c", "echo provider-output"], role="PROVIDER_REVIEW",
                    profile=panel_invoker.SeatProfile(env={"PATH": "/usr/bin:/bin"}),
                    cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                stdout, stderr = proc.communicate()
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    except sandbox_egress.EgressUnavailable:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            raise
        pytest.skip("kernel seat-owner support unavailable")
    assert proc.returncode == 0, stderr.decode(errors="replace")
    assert stdout.strip() == b"provider-output"
    assert _marker_pid(marker) == str(proc.pid)


@pytest.mark.parametrize("caller", ["_leg_auth_ok", "_claude_subscription_auth_ok",
                                   "_claude_code_support_status", "_cleanup_claude_launch_timeout",
                                   "_stop_claude_agent"])
def test_administrative_callers_execute_the_owner_prefix(tmp_path, monkeypatch, caller):
    import json
    import subprocess
    from types import SimpleNamespace

    marker = tmp_path / "ADMIN_PREFIX_RAN"
    responses = {
        "_leg_auth_ok": "Logged in",
        "_claude_subscription_auth_ok": json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                                     "apiProvider": "firstParty", "subscriptionType": "max"}),
        "_claude_code_support_status": "99.0.0",
        "_cleanup_claude_launch_timeout": "[]",
        "_stop_claude_agent": "Stopped",
    }
    original = panel_invoker._seat_command_profile

    @contextmanager
    def stub_profile(_command, **kwargs):
        command = ["/usr/bin/python3", "-I", "-S", "-c", "print(" + repr(responses[caller]) + ")"]
        with original(command, **kwargs) as result:
            yield result

    monkeypatch.setattr(panel_invoker, "_seat_command_profile", stub_profile)
    monkeypatch.chdir(tmp_path)
    with _filtered_marker(marker, monkeypatch, administrative=True) as processes:
        if caller == "_leg_auth_ok":
            assert panel_invoker._leg_auth_ok("codex", {}) == (True, "")
        elif caller == "_claude_subscription_auth_ok":
            assert panel_invoker._claude_subscription_auth_ok({}) == (True, "")
        elif caller == "_claude_code_support_status":
            assert panel_invoker._claude_code_support_status()[0] is True
        elif caller == "_cleanup_claude_launch_timeout":
            adapter = SimpleNamespace(list_command=lambda: ["claude", "agents", "list"])
            assert panel_invoker._cleanup_claude_launch_timeout(
                adapter, cwd=str(tmp_path), env={}, exc=subprocess.TimeoutExpired("fixture", 1),
            ) == "cleanup_none"
        else:
            adapter = SimpleNamespace(stop_command=lambda _id: ["claude", "agents", "stop", "fixture"])
            assert panel_invoker._stop_claude_agent(adapter, "fixture", str(tmp_path), {}) == "stopped"
    _assert_process_marker(marker, processes)


def test_refresh_executes_the_fixed_operation_in_the_observed_process(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import json

    home = tmp_path / "operator"
    credential = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    credential.parent.mkdir(parents=True)
    credential.write_text(json.dumps({"token": {"expiry": "2000-01-01T00:00:00Z"}}))
    marker = tmp_path / "REFRESH_RAN"
    script = tmp_path / "refresh-helper"
    script.write_text("#!/usr/bin/python3\n" +
        "import json,os,pathlib,sys\n" +
        "assert sys.argv[1:] == ['models']\n" +
        "assert list(pathlib.Path.cwd().iterdir()) == []\n" +
        "pathlib.Path(" + repr(str(marker)) + ").write_text('FIRED '+str(os.getpid()))\n" +
        "p=pathlib.Path.home()/'.gemini/antigravity-cli/antigravity-oauth-token'\n" +
        "p.write_text(json.dumps({'token':{'expiry':" +
        repr((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()) + "}}))\n")
    script.chmod(0o700)

    class Image:
        def reopen(self):
            return os.open(script, os.O_RDONLY)

    processes = []
    original = panel_invoker.launch_provider

    def launch(argv, **kwargs):
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()
        process = original(argv, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(panel_invoker, "launch_provider", launch)
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(tmp_path / "MUST_NOT_RUN"))
    try:
        panel_invoker._refresh_gemini_credential(home, Image())
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    _assert_process_marker(marker, processes)
    assert not (tmp_path / "MUST_NOT_RUN").exists()


def test_every_launch_site_has_a_marker_proof_above():
    """Secondary source tripwire; kernel marker tests provide the launch evidence."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(panel_invoker))
    sites = set()

    class References(ast.NodeVisitor):
        def __init__(self):
            self.functions = []

        def visit_FunctionDef(self, node):
            self.functions.append(node.name)
            self.generic_visit(node)
            self.functions.pop()

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in {
                    "launch_provider", "run_provider", "launch_owned"}:
                sites.add(self.functions[-1])
            self.generic_visit(node)

    References().visit(tree)
    assert sites == {
        "launch_owned", "run_provider", "_refresh_gemini_credential", "_leg_auth_ok",
        "_claude_subscription_auth_ok", "_claude_code_support_status",
        "_cleanup_claude_launch_timeout", "_stop_claude_agent", "_popen",
    }, "add a real caller marker proof for every new launch site"
