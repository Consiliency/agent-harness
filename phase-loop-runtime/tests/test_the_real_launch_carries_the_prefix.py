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


class TestTheCLILegLaunch:
    def test_the_prefix_actually_executes_in_front_of_the_provider(self, tmp_path):
        marker = tmp_path / "PREFIX_RAN"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            run = panel_invoker._run_leg_with_liveness(
                ["/bin/sh", "-c", "echo provider-output pid=$$"],
                cwd=tmp_path, env=dict(os.environ), deadline_s=60.0,
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

        assert marker.exists(), (
            "the egress prefix did NOT execute in front of the provider; the launch "
            "reached the kernel without it, whatever the source says"
        )
        assert run.returncode == 0
        stdout = run.stdout if isinstance(run.stdout, str) else run.stdout.decode()
        assert "provider-output" in stdout, (
            "the prefix ran but the real command did not; a wrapper that swallows its "
            "payload would pass the marker check while breaking every seat"
        )
        assert f"pid={_marker_pid(marker)}" in stdout, (
            "the prefix and the provider ran in DIFFERENT processes: something prefixed "
            "an auxiliary command and launched the provider separately"
        )

    def test_no_prefix_means_no_marker(self, tmp_path):
        """The falsifier. If the marker appeared without a prefix it would prove nothing."""
        marker = tmp_path / "PREFIX_RAN"
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()
        run = panel_invoker._run_leg_with_liveness(
            ["/bin/echo", "provider-output"],
            cwd=tmp_path, env=dict(os.environ), deadline_s=60.0,
        )
        assert not marker.exists()
        assert run.returncode == 0


class TestTheHelpersThemselves:
    """Necessary but NOT sufficient -- kept because a helper that stopped prefixing would
    break every route at once, and this localises that failure."""

    def test_launch_provider_executes_the_prefix(self, tmp_path):
        import subprocess as sp

        marker = tmp_path / "LP_RAN"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            proc = panel_invoker.launch_provider(
                ["/bin/echo", "hi"], stdout=sp.PIPE, cwd=str(tmp_path),
            )
            out = proc.communicate(timeout=60)[0].decode()
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        assert marker.exists(), "launch_provider did not execute the prefix"
        assert _marker_pid(marker).isdigit()
        assert out.strip() == "hi"

    def test_run_provider_executes_the_prefix(self, tmp_path):
        marker = tmp_path / "RP_RAN"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            done = panel_invoker.run_provider(
                ["/bin/echo", "hi"], capture_output=True, text=True,
                cwd=str(tmp_path), timeout=60,
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        assert marker.exists(), "run_provider did not execute the prefix"
        assert _marker_pid(marker).isdigit()
        assert done.stdout.strip() == "hi"


class TestTheTUILaunch:
    """The SECOND seam: the Claude TUI leg launches under a PTY via `_run_claude_tui_session`.

    Until agent-harness#890 landed this seam was covered only by a SOURCE check that asserted
    the string `launch_provider(` appeared in the function. That is the proxy pattern this
    file exists to end. The provider here is a shell script that writes a terminal verdict
    to the leg's output file and exits, so the session returns on the normal file-output
    path; the prefix is the same marker wrapper the CLI-leg proof uses.
    """

    @staticmethod
    def _provider(output_file: Path) -> list[str]:
        return [
            "/bin/sh", "-c",
            f"printf 'Reviewed. pid=%s\\n\\nAGREE\\n' $$ > {output_file}; exit 0",
        ]

    def test_the_prefix_actually_executes_in_front_of_the_tui_provider(self, tmp_path):
        marker = tmp_path / "TUI_PREFIX_RAN"
        output_file = tmp_path / "panel-claude.txt"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            rc, text, status, tail = panel_invoker._run_claude_tui_session(
                command=self._provider(output_file),
                cwd=tmp_path,
                prompt="review this",
                output_file=output_file,
                timeout_s=60,
                env={"PATH": "/usr/bin:/bin"},
                backstop_s=60,
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

        assert marker.exists(), (
            "the egress prefix did NOT execute in front of the TUI provider; the PTY "
            f"launch reached the kernel without it (status={status!r} tail={tail!r})"
        )
        assert status == "claude_tui_file_output", (status, tail)
        assert "AGREE" in text, (
            "the prefix ran but the real provider did not write its verdict; a wrapper "
            "that swallows its payload would pass the marker check while breaking the seat"
        )
        assert f"pid={_marker_pid(marker)}" in text, (
            "the prefix and the TUI provider ran in DIFFERENT processes"
        )

    def test_no_prefix_means_no_marker_on_the_tui_seam(self, tmp_path):
        """The falsifier for this seam."""
        marker = tmp_path / "TUI_PREFIX_RAN"
        output_file = tmp_path / "panel-claude.txt"
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()
        _rc, _text, status, _tail = panel_invoker._run_claude_tui_session(
            command=self._provider(output_file),
            cwd=tmp_path,
            prompt="review this",
            output_file=output_file,
            timeout_s=60,
            env={"PATH": "/usr/bin:/bin"},
            backstop_s=60,
        )
        assert not marker.exists()
        assert status == "claude_tui_file_output"


class TestTheAgentViewLaunch:
    """The THIRD seam: `_exec_claude_agent_view_attempt` launches the provider through
    `run_provider`. It has no production caller today; it is proven anyway, because an
    unwired seam that acquires a caller later is a silent hole.

    The fake provider prints a payload and exits non-zero, so the attempt returns on the
    launch-failure branch BEFORE the session-polling loop (which is not a launch seam and
    would otherwise need a fake `claude agents` CLI). The marker proves the prefix executed
    in front of the real launch; the payload in the returned log proves the launch itself
    ran behind the prefix.
    """

    class _Adapter:
        def launch_command(self, _prompt, **_kwargs):
            return ["/bin/sh", "-c", "echo agent-view-payload pid=$$; exit 3"]

    def test_the_prefix_actually_executes_in_front_of_the_agent_view_launch(self, tmp_path):
        marker = tmp_path / "AGENT_VIEW_PREFIX_RAN"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            status, log = panel_invoker._exec_claude_agent_view_attempt(
                self._Adapter(), review_dir=tmp_path, timeout_s=60, prompt="p",
                env={"PATH": "/usr/bin:/bin"},
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

        assert marker.exists(), (
            "the egress prefix did NOT execute in front of the agent-view launch "
            f"(status={status!r} log={log!r})"
        )
        assert "agent-view-payload" in log, (
            "the prefix ran but the real launch did not; a wrapper that swallows its "
            "payload would pass the marker check"
        )
        assert f"pid={_marker_pid(marker)}" in log, (
            "the prefix and the agent-view launch ran in DIFFERENT processes"
        )
        assert status != "OK"

    def test_no_prefix_means_no_marker_on_the_agent_view_seam(self, tmp_path):
        marker = tmp_path / "AGENT_VIEW_PREFIX_RAN"
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()
        status, log = panel_invoker._exec_claude_agent_view_attempt(
            self._Adapter(), review_dir=tmp_path, timeout_s=60, prompt="p",
            env={"PATH": "/usr/bin:/bin"},
        )
        assert not marker.exists()
        assert "agent-view-payload" in log


def test_every_launch_site_has_a_marker_proof_above():
    """A TRIPWIRE, not a proof: the count of conventionally spelled launch-interface call
    sites in `panel_invoker` must equal the number of seams the marker proofs above drive.

    It is spelling-sensitive by construction. `launch = launch_provider; launch(cmd)`, a
    call with a space before the paren, or a call placed in another module all evade it,
    and it associates no site with any function -- it is a cardinality, nothing more. It
    exists so that the ORDINARY way of adding a fourth seam trips a test that says "add a
    marker proof", and for no stronger reason. It does not try to prove "nothing else
    spawns" -- the AST walker that tried (`test_launch_seam_coverage.py`, agent-harness#890
    rounds 7-11) was a Python-only self-scanner the board defeated five times on spelling,
    and it was removed in favour of observing the launches that exist. A raw `subprocess`
    launch of a provider is a review finding, not a test finding.
    """
    import inspect
    import re

    source = inspect.getsource(panel_invoker)
    sites = re.findall(r"^\s+(?:return |proc = )?(?:launch_provider|run_provider)\(", source, flags=re.M)
    proven = {"_run_leg_with_liveness", "_run_claude_tui_session", "_exec_claude_agent_view_attempt"}
    assert len(sites) == len(proven), (
        f"{len(sites)} launch-interface call sites in panel_invoker but marker proofs exist "
        f"for {sorted(proven)}; add a marker proof for the new seam in this file"
    )
