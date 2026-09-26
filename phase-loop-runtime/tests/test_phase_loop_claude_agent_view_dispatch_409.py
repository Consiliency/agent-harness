"""agent-harness#409 / agent-harness#1099: Agent View live dispatch waits for the exact
session it launched and reduces that session's final message, instead of returning as
soon as `claude --bg` starts."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phase_loop_runtime.claude_agent_view import (
    AGENT_VIEW_OBSERVER_FAILURE_LIMIT,
    AgentViewLifecycleResult,
    ClaudeAgentViewAdapter,
    _launch_session_id,
    session_transcript_path,
)
from phase_loop_runtime.launcher import LaunchSpec, _launch_claude_agent_view

ASSIGNED = "0f1e2d3c-4b5a-4968-8776-655443322110"


class _PromptBundle:
    workflow_command = "claude-execute-phase"

    def render_context(self):
        return "workflow context"


def _record(state, *, session_id=ASSIGNED, short=None, cwd="/repo", pid=None):
    return {
        "id": short or session_id[:8],
        "sessionId": session_id,
        "cwd": cwd,
        "kind": "background",
        "state": state,
        **({"pid": pid} if pid else {}),
    }


def _listing_runner(listings, *, launch_stdout=None, calls=None):
    """A fake `claude` runner: --bg --help ok, --bg prints an id, agents lists in turn."""
    queue = list(listings)

    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        if command == ["claude", "--bg", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="Usage: claude\n")
        if command[:2] == ["claude", "--bg"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=launch_stdout if launch_stdout is not None else f"backgrounded · {ASSIGNED[:8]}\n"
            )
        if command == ["claude", "agents", "--json", "--all"]:
            current = queue.pop(0) if len(queue) > 1 else queue[0]
            if current is None:
                return subprocess.CompletedProcess(command, 1, stdout="daemon unavailable")
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(current))
        if command[:2] == ["claude", "stop"]:
            return subprocess.CompletedProcess(command, 0, stdout="")
        raise AssertionError(f"unexpected command: {command}")

    return run


class _Clock:
    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += self.step


class LaunchCommandTest(unittest.TestCase):
    def test_launch_command_carries_tool_policy_and_never_renders_cwd_or_session_id(self):
        command = ClaudeAgentViewAdapter().launch_command(
            "do work",
            cwd="/repo",
            permission="bypassPermissions",
            allowed_tools="Bash,Read",
            disallowed_tools="AskUserQuestion",
        )
        # The root `claude` command has no --cwd option; rendering it fails the launch.
        self.assertNotIn("--cwd", command)
        # `claude --bg` ignores --session-id ("--bg manages the session id"), so binding
        # uses the printed id instead.
        self.assertNotIn("--session-id", command)
        self.assertEqual(command[command.index("--allowedTools") + 1], "Bash,Read")
        self.assertEqual(command[command.index("--disallowedTools") + 1], "AskUserQuestion")
        # The prompt follows the end-of-options marker, so a variadic option such as
        # --disallowedTools cannot swallow it (the failed agent-harness#1099 proof run).
        self.assertEqual(command[-2:], ["--", "do work"])

    def test_variadic_options_never_precede_a_bare_prompt(self):
        variadic = {"--tools", "--allowedTools", "--disallowedTools", "--add-dir"}
        command = ClaudeAgentViewAdapter().launch_command(
            "do work", tools="Read", allowed_tools="Bash", disallowed_tools="Agent", add_dirs=["/ctx"]
        )
        prompt_at = command.index("do work")
        self.assertEqual(command[prompt_at - 1], "--")
        self.assertTrue(variadic & set(command[:prompt_at]))

    def test_launch_session_id_parses_the_backgrounded_banner(self):
        self.assertEqual(_launch_session_id("backgrounded · 1a2b3c4d\n"), "1a2b3c4d")
        self.assertEqual(_launch_session_id("run `claude attach 1a2b3c4d` to reopen"), "1a2b3c4d")


class LaunchBindingTest(unittest.TestCase):
    def _launch(self, runner):
        adapter = ClaudeAgentViewAdapter(runner=runner)
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"):
            return adapter.launch_background("do work", cwd="/repo", bind_printed_id=True)

    def test_another_session_in_the_same_cwd_is_never_adopted(self):
        # The #409 trace: two records for the worktree and the adapter guessed.
        other = _record("done", session_id="99999999-0000-4000-8000-000000000000")
        lifecycle = self._launch(_listing_runner([[other]]))
        self.assertEqual(lifecycle.session_id, ASSIGNED[:8])
        self.assertEqual(lifecycle.state, "running")
        self.assertIsNone(lifecycle.blocker)

    def test_the_printed_session_is_bound_to_its_full_id_once_listed(self):
        other = _record("done", session_id="99999999-0000-4000-8000-000000000000")
        lifecycle = self._launch(_listing_runner([[other, _record("working")]]))
        self.assertEqual(lifecycle.session_id, ASSIGNED)
        self.assertEqual(lifecycle.state, "running")

    def test_no_printed_id_fails_closed(self):
        lifecycle = self._launch(_listing_runner([[_record("working")]], launch_stdout="started\n"))
        self.assertEqual(lifecycle.state, "blocked")
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_unbound")

    def test_cli_refusal_line_is_surfaced(self):
        # The host precondition that blocked the agent-harness#1099 proof runs.
        refusal = ("--bg with bypassPermissions requires accepting the disclaimer first. "
                   "Run `claude --dangerously-skip-permissions` once interactively.")

        def run(command, **kwargs):
            if command == ["claude", "--bg", "--help"]:
                return subprocess.CompletedProcess(command, 0, stdout="Usage: claude\n")
            return subprocess.CompletedProcess(command, 1, stdout=refusal + "\nsecret transcript line\n")

        lifecycle = self._launch(run)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_launch_failed")
        self.assertIn("requires accepting the disclaimer", lifecycle.blocker.summary)
        self.assertNotIn("secret transcript", lifecycle.blocker.summary)


class WaitForTerminalTest(unittest.TestCase):
    def _wait(self, listings, **kwargs):
        clock = _Clock(step=kwargs.pop("step", 5.0))
        polled = []
        adapter = ClaudeAgentViewAdapter(runner=_listing_runner(listings))
        lifecycle = adapter.wait_for_terminal(
            ASSIGNED, cwd="/repo", sleep=clock.sleep, clock=clock, on_poll=polled.append, **kwargs
        )
        return lifecycle, polled

    def test_waits_through_running_until_done(self):
        lifecycle, polled = self._wait([[_record("working")], [_record("working")], [_record("done")]])
        self.assertEqual(lifecycle.state, "done")
        self.assertEqual(lifecycle.session_id, ASSIGNED)
        self.assertEqual(len(polled), 3)

    def test_no_default_deadline_even_after_a_very_long_run(self):
        # One poll per simulated day; a slow session is never timed out by default.
        listings = [[_record("working")]] * 30 + [[_record("done")]]
        lifecycle, _ = self._wait(listings, step=86400.0)
        self.assertEqual(lifecycle.state, "done")
        self.assertIsNone(lifecycle.blocker)

    def test_blocked_session_returns_without_being_stopped(self):
        calls = []
        adapter = ClaudeAgentViewAdapter(runner=_listing_runner([[_record("blocked")]], calls=calls))
        clock = _Clock(step=5.0)
        lifecycle = adapter.wait_for_terminal(ASSIGNED, cwd="/repo", sleep=clock.sleep, clock=clock)
        self.assertEqual(lifecycle.state, "blocked")
        self.assertFalse(any(command[:2] == ["claude", "stop"] for command in calls))

    def test_observer_failure_fails_closed_after_the_limit(self):
        lifecycle, polled = self._wait([None])
        self.assertEqual(lifecycle.state, "blocked")
        self.assertEqual(lifecycle.blocker.reason, "agents_list_failed")
        self.assertEqual(len(polled), AGENT_VIEW_OBSERVER_FAILURE_LIMIT)

    def test_a_listed_session_resets_the_observer_failure_count(self):
        listings = [None] * (AGENT_VIEW_OBSERVER_FAILURE_LIMIT - 1) + [[_record("working")]]
        listings += [None] * (AGENT_VIEW_OBSERVER_FAILURE_LIMIT - 1) + [[_record("done")]]
        lifecycle, _ = self._wait(listings)
        self.assertEqual(lifecycle.state, "done")

    def test_explicit_timeout_is_honored(self):
        lifecycle, _ = self._wait([[_record("working")]], timeout_s=12.0)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_launch_timeout")


class TranscriptPathTest(unittest.TestCase):
    def test_exact_project_dir_then_unique_session_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exact = root / "-repo" / f"{ASSIGNED}.jsonl"
            exact.parent.mkdir()
            exact.write_text("{}\n", encoding="utf-8")
            by_cwd = lambda cwd: root / cwd.replace("/", "-")  # noqa: E731
            self.assertEqual(session_transcript_path(ASSIGNED, cwd="/repo", project_dir_for_cwd=by_cwd, projects_root=root), exact)
            # A different spelling of the cwd (e.g. a symlink) still finds the unique id.
            self.assertEqual(session_transcript_path(ASSIGNED, cwd="/elsewhere", project_dir_for_cwd=by_cwd, projects_root=root), exact)
            self.assertIsNone(session_transcript_path(
                "11111111-2222-4333-8444-555555555555", cwd="/repo", project_dir_for_cwd=by_cwd, projects_root=root
            ))


class _ScriptedAdapter(ClaudeAgentViewAdapter):
    def __init__(self, *, launch_state="running", terminal_state="done", text="final", blocker=None):
        super().__init__(runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess")))
        self.launch_state = launch_state
        self.terminal_state = terminal_state
        self.text = text
        self.terminal_blocker = blocker
        self.launch_kwargs = None
        self.prompt = None
        self.stopped = []
        self.wait_kwargs = None

    def _lifecycle(self, state, blocker=None):
        return AgentViewLifecycleResult(
            session_id="agent-1", state=state, cwd="/repo", logs_ref=None,
            started_at=None, completed_at=None, stop_result=None, blocker=blocker,
        )

    def launch_background(self, prompt, *, cwd, **kwargs):
        self.prompt = prompt
        self.launch_kwargs = kwargs
        return self._lifecycle(self.launch_state)

    def wait_for_terminal(self, session_id, *, cwd=None, **kwargs):
        self.wait_kwargs = kwargs
        kwargs["on_poll"](None)
        return self._lifecycle(self.terminal_state, self.terminal_blocker)

    def final_text(self, session_id, *, cwd):
        return self.text

    def stop(self, agent_id, *, cwd=None):
        self.stopped.append(agent_id)
        return self._lifecycle("stopped")


class LaunchClaudeAgentViewTest(unittest.TestCase):
    def _run(self, adapter, *, timeout=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run_dir = Path(tmp.name) / "run"
        spec = LaunchSpec(
            executor="claude",
            command=["claude", "--bg", "--permission-mode", "bypassPermissions",
                     "--allowedTools", "Bash,Read", "--disallowedTools", "AskUserQuestion", "x"],
            prompt_bundle=_PromptBundle(),
            injection_metadata=None,
            delivery_mode="agent_view",
            dispatch_decision=None,
            available=True,
            selected_model="claude-opus-5-5",
            selected_effort="high",
            wrapped_cwd=tmp.name,
            claude_route="claude_agent_view",
            launch_timeout_seconds=timeout,
        )
        result = _launch_claude_agent_view(
            spec, log_path=run_dir / "launch.log", heartbeat_path=run_dir / "heartbeat.json", adapter=adapter
        )
        return result, run_dir

    def test_done_session_returns_its_final_message_as_the_launch_output(self):
        adapter = _ScriptedAdapter(text="automation:\n  status: complete")
        result, run_dir = self._run(adapter)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.output, "automation:\n  status: complete")
        self.assertEqual(result.claude_route_result["status"], "done")
        self.assertEqual((run_dir / "launch.log").read_text(encoding="utf-8"), "automation:\n  status: complete\n")
        # The context goes through a file, not a single argv entry.
        self.assertEqual((run_dir / "context.md").read_text(encoding="utf-8"), "workflow context\n")
        self.assertIn(str(run_dir / "context.md"), adapter.prompt)
        self.assertEqual(adapter.launch_kwargs["add_dirs"], [run_dir])
        # The session is bound by its printed id and the spec's tool policy is carried.
        self.assertTrue(adapter.launch_kwargs["bind_printed_id"])
        self.assertNotIn("--session-id", result.command)
        self.assertEqual(result.command[-2], "--")
        self.assertEqual(adapter.launch_kwargs["allowed_tools"], "Bash,Read")
        self.assertEqual(adapter.launch_kwargs["disallowed_tools"], "AskUserQuestion")
        self.assertEqual(adapter.launch_kwargs["permission"], "bypassPermissions")
        # No deadline unless the operator configured one.
        self.assertIsNone(adapter.wait_kwargs["timeout_s"])
        self.assertTrue((run_dir / "heartbeat.json").is_file())

    def test_running_is_never_reported_as_a_successful_launch(self):
        # The exact #409 failure: the runner saw rc=0 for a session that was still running.
        adapter = _ScriptedAdapter(terminal_state="unknown", blocker=None)
        result, _ = self._run(adapter)
        self.assertEqual(result.returncode, 1)

    def test_done_without_a_readable_final_message_fails_closed(self):
        result, _ = self._run(_ScriptedAdapter(text=""))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.claude_route_result["status"], "blocked")
        self.assertIn("could not be read", result.output)

    def test_needs_input_is_blocked_and_left_attachable(self):
        adapter = _ScriptedAdapter(terminal_state="blocked")
        result, _ = self._run(adapter)
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude attach", result.output)
        self.assertEqual(adapter.stopped, [])

    def test_operator_timeout_stops_the_session(self):
        from phase_loop_runtime.claude_agent_view import BlockerSummary

        adapter = _ScriptedAdapter(
            terminal_state="unknown", blocker=BlockerSummary("agent_view_launch_timeout", "timed out")
        )
        result, _ = self._run(adapter, timeout=60)
        self.assertEqual(adapter.wait_kwargs["timeout_s"], 60.0)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.timed_out)
        self.assertEqual(adapter.stopped, ["agent-1"])


if __name__ == "__main__":
    unittest.main()
