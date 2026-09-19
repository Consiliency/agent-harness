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
    """A prefix that RUNS: it writes `marker`, then execs whatever follows it.

    Chosen over a recording shim deliberately. Anything that merely records an argv is
    another proxy -- it proves what was passed to a function, not what a kernel executed.
    The marker exists only if this wrapper actually ran in front of the real command.
    """
    return ("/bin/sh", "-c", f'echo FIRED > {marker}; exec "$@"', "--")


class TestTheCLILegLaunch:
    def test_the_prefix_actually_executes_in_front_of_the_provider(self, tmp_path):
        marker = tmp_path / "PREFIX_RAN"
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(_marker_prefix(marker))
        try:
            run = panel_invoker._run_leg_with_liveness(
                ["/bin/echo", "provider-output"],
                cwd=tmp_path, env=dict(os.environ), deadline_s=60.0,
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

        assert marker.exists(), (
            "the egress prefix did NOT execute in front of the provider; the launch "
            "reached the kernel without it, whatever the source says"
        )
        assert marker.read_text(encoding="utf-8").strip() == "FIRED"
        assert run.returncode == 0
        stdout = run.stdout if isinstance(run.stdout, str) else run.stdout.decode()
        assert "provider-output" in stdout, (
            "the prefix ran but the real command did not; a wrapper that swallows its "
            "payload would pass the marker check while breaking every seat"
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
        assert done.stdout.strip() == "hi"


def test_the_tui_seam_is_not_covered_here_and_says_so():
    """An honest gap rather than a silent one.

    codex asked for the TUI route to be included. It launches under a PTY with a real
    provider binary, so driving it in a unit test would need a fake `claude` on PATH and a
    pty pair. It is NOT covered by the marker probe above, and pretending otherwise is the
    failure this file exists to end. Tracked as the remaining gap in agent-harness#890.
    """
    import inspect

    source = inspect.getsource(panel_invoker._run_claude_tui_session)
    assert "launch_provider(" in source, (
        "the TUI seam no longer routes through the interface, and nothing here would "
        "have caught that -- this assertion is a SOURCE check and is labelled as one"
    )
