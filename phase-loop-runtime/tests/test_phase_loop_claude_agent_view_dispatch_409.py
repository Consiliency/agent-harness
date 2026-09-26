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
    AGENT_VIEW_LISTING_ERROR_LIMIT,
    AGENT_VIEW_OBSERVER_FAILURE_LIMIT,
    AGENT_VIEW_SNAPSHOT_ATTEMPTS,
    claude_global_config_path,
    workspace_folder_trust,
    workspace_trust_state,
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
        # --disallowedTools cannot swallow it.
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


class LaunchSpecPermissionTest(unittest.TestCase):
    """agent-harness#1101 round 1 (claude B1, grok): the route adds no permission grant."""

    def test_non_bypass_agent_view_spec_renders_no_allow_rules(self):
        from _launchspec_golden_cases import _pinned_claude_eligibility, _pinned_env
        from phase_loop_runtime.launcher import build_launch_request, build_launch_spec
        from phase_loop_runtime.profiles import resolve_profile_for_executor
        from phase_loop_runtime.prompts import build_prompt

        roadmap = Path("/repo/specs/phase-plans-v1.md")
        for action in ("plan", "roadmap", "execute", "repair"):
            with self.subTest(action=action), _pinned_env():
                spec = build_launch_spec(build_launch_request(
                    executor="claude", action=action, repo=Path("/repo"), roadmap=roadmap, phase="ADAPTER",
                    plan=Path("/repo/plans/phase-plan-v1-ADAPTER.md"),
                    model_selection=resolve_profile_for_executor(action=action, executor="claude"),
                    prompt_bundle=build_prompt(action, roadmap, phase="ADAPTER"),
                    json_output=True, bypass_approvals=False,
                    claude_execution_mode="solo", phase_team_eligibility=_pinned_claude_eligibility(),
                ))
                self.assertEqual(spec.claude_route, "claude_agent_view")
                self.assertNotIn("--allowedTools", spec.command)
                self.assertNotIn("--dangerously-skip-permissions", spec.command)
                self.assertIn("--disallowedTools", spec.command)
                # Round 2 (codex B2): no mode at all without an explicit request, so the
                # session inherits the operator's own configured mode.
                self.assertNotIn("--permission-mode", spec.command)
                # `--` immediately before the prompt, which is last (claude N5).
                self.assertEqual(spec.command[-2], "--")
                self.assertNotIn("--add-dir", spec.command)

    def test_explicit_bypass_is_the_only_permission_mode_passed(self):
        from _launchspec_golden_cases import _pinned_claude_eligibility, _pinned_env
        from phase_loop_runtime.launcher import build_launch_request, build_launch_spec
        from phase_loop_runtime.profiles import resolve_profile_for_executor
        from phase_loop_runtime.prompts import build_prompt

        roadmap = Path("/repo/specs/phase-plans-v1.md")
        for action in ("plan", "roadmap", "execute", "repair"):
            with self.subTest(action=action), _pinned_env():
                spec = build_launch_spec(build_launch_request(
                    executor="claude", action=action, repo=Path("/repo"), roadmap=roadmap, phase="ADAPTER",
                    plan=Path("/repo/plans/phase-plan-v1-ADAPTER.md"),
                    model_selection=resolve_profile_for_executor(action=action, executor="claude"),
                    prompt_bundle=build_prompt(action, roadmap, phase="ADAPTER"),
                    json_output=True, bypass_approvals=True,
                    claude_execution_mode="solo", phase_team_eligibility=_pinned_claude_eligibility(),
                ))
                mode_at = spec.command.index("--permission-mode")
                self.assertEqual(spec.command[mode_at + 1], "bypassPermissions")
                # The mode is an option, so it must precede the end-of-options marker.
                self.assertLess(mode_at, spec.command.index("--"))
                self.assertEqual(spec.command[-2], "--")
                self.assertNotIn("--add-dir", spec.command)
                self.assertNotIn("--allowedTools", spec.command)


class LaunchBindingTest(unittest.TestCase):
    def setUp(self):
        # Folder trust is covered by FolderTrustTest; these tests are about the lifecycle.
        patcher = mock.patch("phase_loop_runtime.claude_agent_view.workspace_folder_trust", return_value="trusted")
        patcher.start()
        self.addCleanup(patcher.stop)

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
        lifecycle = self._launch(_listing_runner([[other], [other, _record("working")]]))
        self.assertEqual(lifecycle.session_id, ASSIGNED)
        self.assertEqual(lifecycle.state, "running")

    def test_no_printed_id_fails_closed(self):
        lifecycle = self._launch(_listing_runner([[_record("working")]], launch_stdout="started\n"))
        self.assertEqual(lifecycle.state, "blocked")
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_unbound")

    def test_cli_refusal_line_is_surfaced(self):
        # Any CLI refusal line is surfaced; this one is a real --bg precondition message.
        refusal = ("--bg with bypassPermissions requires accepting the disclaimer first. "
                   "Run `claude --dangerously-skip-permissions` once interactively.")

        def run(command, **kwargs):
            if command == ["claude", "--bg", "--help"]:
                return subprocess.CompletedProcess(command, 0, stdout="Usage: claude\n")
            if command == ["claude", "agents", "--json", "--all"]:
                return subprocess.CompletedProcess(command, 0, stdout="[]")
            return subprocess.CompletedProcess(command, 1, stdout=refusal + "\nsecret transcript line\n")

        lifecycle = self._launch(run)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_launch_failed")
        self.assertIn("requires accepting the disclaimer", lifecycle.blocker.summary)
        self.assertNotIn("secret transcript", lifecycle.blocker.summary)

    def test_any_first_refusal_line_is_surfaced_ansi_stripped(self):
        def run(command, **kwargs):
            if command == ["claude", "--bg", "--help"]:
                return subprocess.CompletedProcess(command, 0, stdout="Usage: claude\n")
            if command == ["claude", "agents", "--json", "--all"]:
                return subprocess.CompletedProcess(command, 0, stdout="[]")
            return subprocess.CompletedProcess(command, 1, stdout="\n\x1b[31mmodel not available\x1b[39m\nmore\n")

        lifecycle = self._launch(run)
        self.assertTrue(lifecycle.blocker.summary.endswith(" CLI: model not available"))


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

    def test_listing_outage_fails_closed_after_the_longer_limit_and_names_the_live_session(self):
        lifecycle, polled = self._wait([[_record("working")], None])
        self.assertEqual(lifecycle.state, "blocked")
        self.assertEqual(lifecycle.blocker.reason, "agents_list_failed")
        self.assertEqual(len(polled), 1 + AGENT_VIEW_LISTING_ERROR_LIMIT)
        # The observer gave up, not the session: say so, with the pinned full id.
        self.assertIn("may still be running", lifecycle.blocker.summary)
        self.assertIn(f"claude attach {ASSIGNED}", lifecycle.blocker.summary)
        self.assertIn(f"claude stop {ASSIGNED}", lifecycle.blocker.summary)

    def test_missing_record_fails_closed_after_the_shorter_limit(self):
        lifecycle, polled = self._wait([[]])
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_missing")
        self.assertEqual(len(polled), AGENT_VIEW_OBSERVER_FAILURE_LIMIT)
        self.assertIn("may still be running", lifecycle.blocker.summary)

    def test_a_record_that_registers_before_the_limit_is_bound(self):
        # The missing count runs from launch: polls before first registration count.
        listings = [[]] * (AGENT_VIEW_OBSERVER_FAILURE_LIMIT - 1) + [[_record("working")], [_record("done")]]
        lifecycle, polled = self._wait(listings)
        self.assertEqual(lifecycle.state, "done")
        self.assertEqual(len(polled), AGENT_VIEW_OBSERVER_FAILURE_LIMIT + 1)

    def test_a_record_that_never_registers_fails_closed_at_the_limit(self):
        lifecycle, polled = self._wait([[]] * AGENT_VIEW_OBSERVER_FAILURE_LIMIT + [[_record("done")]])
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_missing")
        self.assertEqual(len(polled), AGENT_VIEW_OBSERVER_FAILURE_LIMIT)

    def test_listing_errors_neither_add_to_nor_reset_the_missing_count(self):
        limit = AGENT_VIEW_OBSERVER_FAILURE_LIMIT
        listings = [[]] * (limit - 1) + [None] * 5 + [[]]
        lifecycle, polled = self._wait(listings)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_missing")
        self.assertEqual(len(polled), limit + 5)

    def test_a_listed_session_resets_the_observer_failure_count(self):
        listings = [[]] * (AGENT_VIEW_OBSERVER_FAILURE_LIMIT - 1) + [[_record("working")]]
        listings += [None] * (AGENT_VIEW_LISTING_ERROR_LIMIT - 1) + [[_record("done")]]
        lifecycle, _ = self._wait(listings)
        self.assertEqual(lifecycle.state, "done")

    def test_explicit_timeout_is_honored(self):
        lifecycle, _ = self._wait([[_record("working")]], timeout_s=12.0)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_launch_timeout")


class AmbiguousBindingTest(unittest.TestCase):
    """agent-harness#1101 round 1 (codex): a short id shared by two listed sessions."""

    OLDER = "0f1e2d3c-0000-4000-8000-000000000001"

    def test_launch_refuses_an_ambiguous_short_id(self):
        # Neither record was listed before the launch, so neither is excluded.
        listing = [_record("done", session_id=self.OLDER), _record("working")]
        adapter = ClaudeAgentViewAdapter(runner=_listing_runner([[], listing]))
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"), \
                mock.patch("phase_loop_runtime.claude_agent_view.workspace_folder_trust", return_value="trusted"):
            lifecycle = adapter.launch_background("do work", cwd="/repo", bind_printed_id=True)
        self.assertEqual(lifecycle.state, "blocked")
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_ambiguous")
        self.assertIn("may still be running", lifecycle.blocker.summary)

    NONCE = "5a1f0c7e-1111-4222-8333-944455556666"

    def _launch_then_wait(self, listings, *, nonce=None, transcripts=None):
        """Launch + wait against scripted listings. With `nonce`, `transcripts` maps a
        full session id to its first user turn, written as a real JSONL transcript."""
        clock = _Clock(step=5.0)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for sid, first_user in (transcripts or {}).items():
            path = root / "-some-project" / f"{sid}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"type": "user", "uuid": "u1", "message": {"role": "user", "content": first_user}}) + "\n",
                            encoding="utf-8")
        adapter = ClaudeAgentViewAdapter(runner=_listing_runner(listings), projects_root=root, sleep=lambda s: None)
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"), \
                mock.patch("phase_loop_runtime.claude_agent_view.workspace_folder_trust", return_value="trusted"), \
                mock.patch("phase_loop_runtime.panel_invoker._claude_project_dir_for_cwd", return_value=root / "absent"):
            launched = adapter.launch_background("do work", cwd="/repo", bind_printed_id=True, launch_nonce=nonce)
            if launched.blocker is not None:
                return launched, launched
            waited = adapter.wait_for_terminal(
                launched.session_id, cwd="/repo", exclude=launched.preexisting_session_ids,
                verified=launched.binding_verified, nonce=nonce, sleep=clock.sleep, clock=clock,
                # A simulated operator bound, so a broken binding FAILS the test instead
                # of spinning forever (the real route has no default deadline).
                timeout_s=86400.0,
            )
        return launched, waited

    def _ours(self):
        return {ASSIGNED: f"run the phase\n\nphase-loop-launch-nonce: {self.NONCE}"}

    def test_a_preexisting_same_prefix_session_is_never_bound_when_the_new_one_registers_late(self):
        # Round 2 (codex B1): the older `done` record is ALONE in the listings until the
        # new session registers; it must never be bound or reduced.
        older = _record("done", session_id=self.OLDER)
        launched, waited = self._launch_then_wait([
            [older],                          # pre-launch snapshot
            [older],                          # launch-time lookup: new one not listed yet
            [older],                          # wait poll 1: still not registered
            [older, _record("working")],      # wait poll 2: registered
            [older, _record("done")],         # wait poll 3: finished
        ], nonce=self.NONCE, transcripts={**self._ours(), self.OLDER: f"phase-loop-launch-nonce: {self.NONCE}"})
        self.assertEqual(launched.state, "running")
        self.assertEqual(launched.session_id, ASSIGNED[:8])
        self.assertEqual(launched.preexisting_session_ids, frozenset({self.OLDER}))
        self.assertEqual(waited.state, "done")
        self.assertEqual(waited.session_id, ASSIGNED)

    def test_a_preexisting_same_prefix_session_alone_fails_closed_never_succeeds(self):
        older = _record("done", session_id=self.OLDER)
        _, waited = self._launch_then_wait([[older]], nonce=self.NONCE, transcripts=self._ours())
        self.assertNotEqual(waited.state, "done")
        self.assertEqual(waited.blocker.reason, "agent_view_session_missing")
        self.assertEqual(waited.session_id, ASSIGNED[:8])

    def test_round4_unfinished_impostor_is_never_reported_and_ours_binds(self):
        # Round 4 (codex): empty snapshot; unrelated B, same short id, same cwd, still
        # WORKING when first seen, registers before A. B's transcript lacks the nonce.
        impostor = _record("working", session_id=self.OLDER)
        launched, waited = self._launch_then_wait([
            [],                                         # snapshot
            [impostor],                                 # launch lookup: only B (working)
            [dict(impostor, state="done")],             # wait 1: B finishes; A not listed yet
            [dict(impostor, state="done"), _record("working")],   # wait 2: A registers
            [dict(impostor, state="done"), _record("done")],      # wait 3: A done
        ], nonce=self.NONCE, transcripts={**self._ours(), self.OLDER: "some other task"})
        self.assertEqual(launched.state, "running")
        self.assertIn(self.OLDER, launched.preexisting_session_ids)   # proven not ours, excluded
        self.assertEqual(waited.state, "done")
        self.assertEqual(waited.session_id, ASSIGNED)

    def test_round4_unfinished_impostor_alone_never_succeeds(self):
        impostor = _record("working", session_id=self.OLDER)
        _, waited = self._launch_then_wait(
            [[], [impostor], [dict(impostor, state="done")]],
            nonce=self.NONCE, transcripts={self.OLDER: "some other task"},
        )
        self.assertNotEqual(waited.state, "done")
        self.assertEqual(waited.blocker.reason, "agent_view_session_missing")
        self.assertNotEqual(waited.session_id, self.OLDER)

    def test_our_session_already_finished_when_first_seen_is_accepted_by_its_nonce(self):
        # The nonce replaces the round-3 first-sight guard's false refusal of our own
        # fast session.
        launched, waited = self._launch_then_wait(
            [[], [], [_record("done")]], nonce=self.NONCE, transcripts=self._ours()
        )
        self.assertEqual(waited.state, "done")
        self.assertEqual(waited.session_id, ASSIGNED)
        self.assertIsNone(waited.blocker)

    def test_an_unreadable_transcript_stays_unproven_then_fails_closed(self):
        launched, waited = self._launch_then_wait([[], [_record("working")]], nonce=self.NONCE, transcripts={})
        self.assertEqual(waited.blocker.reason, "agent_view_binding_unverifiable")
        self.assertEqual(waited.session_id, ASSIGNED[:8])
        self.assertNotEqual(waited.state, "done")

    def test_legacy_without_nonce_refuses_a_candidate_finished_at_first_sight(self):
        other = _record("done", session_id=self.OLDER)
        launched, _ = self._launch_then_wait([[], [other]])
        self.assertEqual(launched.blocker.reason, "agent_view_binding_unverifiable")
        # The run record names the printed id, not the rejected candidate (claude N3).
        self.assertEqual(launched.session_id, ASSIGNED[:8])
        self.assertNotEqual(launched.session_id, self.OLDER)

    def test_a_same_prefix_session_in_another_cwd_never_matches(self):
        elsewhere = _record("done", session_id=self.OLDER, cwd="/elsewhere")
        launched, waited = self._launch_then_wait([
            [],                                       # snapshot
            [elsewhere],                              # launch lookup: only the other-cwd one
            [elsewhere, _record("working")],          # A registers
            [elsewhere, _record("done")],
        ], nonce=self.NONCE, transcripts={**self._ours(), self.OLDER: f"phase-loop-launch-nonce: {self.NONCE}"})
        self.assertEqual(launched.state, "running")
        self.assertEqual(waited.state, "done")
        self.assertEqual(waited.session_id, ASSIGNED)

    def test_cwd_is_compared_by_realpath_and_empty_cwd_is_unknown(self):
        from phase_loop_runtime.claude_agent_view import _same_dir

        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real)
            self.assertTrue(_same_dir(str(link), str(real)))
        self.assertFalse(_same_dir("", "/repo"))
        self.assertFalse(_same_dir(None, "/repo"))

    def test_after_pinning_the_cwd_filter_no_longer_applies(self):
        # claude N2: once proven and pinned, a changed listed cwd does not drop the session.
        moved = _record("done", cwd="/repo/sub")
        launched, waited = self._launch_then_wait(
            [[], [_record("working")], [moved]], nonce=self.NONCE, transcripts=self._ours()
        )
        self.assertTrue(launched.binding_verified)
        self.assertEqual(waited.state, "done")

    def test_launch_refuses_before_starting_when_existing_sessions_cannot_be_listed(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if command == ["claude", "--bg", "--help"]:
                return subprocess.CompletedProcess(command, 0, stdout="Usage\n")
            if command == ["claude", "agents", "--json", "--all"]:
                return subprocess.CompletedProcess(command, 1, stdout="down")
            raise AssertionError(f"launched despite unknown pre-existing sessions: {command}")

        slept = []
        adapter = ClaudeAgentViewAdapter(runner=run, sleep=slept.append)
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"), \
                mock.patch("phase_loop_runtime.claude_agent_view.workspace_folder_trust", return_value="trusted"):
            lifecycle = adapter.launch_background("do work", cwd="/repo", bind_printed_id=True)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_preexisting_unknown")
        # A bounded retry, then refusal: AGENT_VIEW_SNAPSHOT_ATTEMPTS listings, no launch.
        self.assertEqual(calls.count(["claude", "agents", "--json", "--all"]), AGENT_VIEW_SNAPSHOT_ATTEMPTS)
        self.assertEqual(len(slept), AGENT_VIEW_SNAPSHOT_ATTEMPTS - 1)

    def test_a_transient_snapshot_failure_is_retried_then_launches(self):
        listings = iter([None, None, [], [_record("working")]])

        def run(command, **kwargs):
            if command == ["claude", "--bg", "--help"]:
                return subprocess.CompletedProcess(command, 0, stdout="Usage\n")
            if command == ["claude", "agents", "--json", "--all"]:
                current = next(listings)
                if current is None:
                    return subprocess.CompletedProcess(command, 1, stdout="down")
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(current))
            return subprocess.CompletedProcess(command, 0, stdout=f"backgrounded · {ASSIGNED[:8]}\n")

        adapter = ClaudeAgentViewAdapter(runner=run, sleep=lambda s: None)
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"), \
                mock.patch("phase_loop_runtime.claude_agent_view.workspace_folder_trust", return_value="trusted"):
            lifecycle = adapter.launch_background("do work", cwd="/repo", bind_printed_id=True)
        self.assertIsNone(lifecycle.blocker)
        self.assertEqual(lifecycle.session_id, ASSIGNED)

    def test_wait_refuses_an_ambiguous_short_id_instead_of_reducing_the_older_session(self):
        clock = _Clock(step=5.0)
        listing = [_record("done", session_id=self.OLDER), _record("working")]
        adapter = ClaudeAgentViewAdapter(runner=_listing_runner([listing]))
        lifecycle = adapter.wait_for_terminal(ASSIGNED[:8], cwd="/repo", sleep=clock.sleep, clock=clock)
        self.assertEqual(lifecycle.blocker.reason, "agent_view_session_ambiguous")
        self.assertNotEqual(lifecycle.state, "done")

    def test_once_resolved_the_full_id_is_pinned(self):
        # Poll 1 resolves the short id uniquely; poll 2 adds an older `done` record that
        # shares it. The pinned full id keeps the wait on the launched session.
        clock = _Clock(step=5.0)
        listings = [
            [_record("working")],
            [_record("done", session_id=self.OLDER), _record("working")],
            [_record("done", session_id=self.OLDER), _record("done")],
        ]
        adapter = ClaudeAgentViewAdapter(runner=_listing_runner(listings))
        lifecycle = adapter.wait_for_terminal(ASSIGNED[:8], cwd="/repo", sleep=clock.sleep, clock=clock)
        self.assertEqual(lifecycle.state, "done")
        self.assertEqual(lifecycle.session_id, ASSIGNED)
        self.assertEqual(clock.now, 10.0)

    def test_strict_parse_ignores_other_session_mentions_and_ansi(self):
        self.assertEqual(_launch_session_id("backgrounded · \x1b[36m93efedda\x1b[39m\n", strict=True), "93efedda")
        self.assertEqual(_launch_session_id("backgrounded · 93efedda.\n", strict=True), "93efedda")
        self.assertEqual(_launch_session_id("backgrounded · 93efedda: started\n", strict=True), "93efedda")
        self.assertIsNone(_launch_session_id("session: deadbeef finished earlier\n", strict=True))
        self.assertIsNone(_launch_session_id(json.dumps({"id": "deadbeef"}), strict=True))

    def test_launch_subprocess_runs_in_the_workspace(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs.get("cwd")))
            if command == ["claude", "--bg", "--help"]:
                return subprocess.CompletedProcess(command, 0, stdout="Usage\n")
            if command[:2] == ["claude", "--bg"]:
                return subprocess.CompletedProcess(command, 0, stdout=f"backgrounded · {ASSIGNED[:8]}\n")
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps([_record("working")]))

        adapter = ClaudeAgentViewAdapter(runner=run)
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"), \
                mock.patch("phase_loop_runtime.claude_agent_view.workspace_folder_trust", return_value="trusted"):
            adapter.launch_background("do work", cwd="/work/repo", bind_printed_id=True)
        launch_cwds = [cwd for command, cwd in calls if command[:2] == ["claude", "--bg"] and command != ["claude", "--bg", "--help"]]
        self.assertEqual(launch_cwds, ["/work/repo"])


class RealTranscriptReadTest(unittest.TestCase):
    """agent-harness#1101 round 1 (claude N2, codex): the real final-message read path."""

    def _write(self, root, cwd, records):
        from phase_loop_runtime.panel_invoker import _claude_project_dir_for_cwd

        project = root / _claude_project_dir_for_cwd(cwd).name
        project.mkdir(parents=True)
        path = project / f"{ASSIGNED}.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        return path

    def _run(self, records):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        projects = home / ".claude" / "projects"
        self._write(projects, "/work/repo", records)
        with mock.patch.dict("os.environ", {"HOME": str(home)}), mock.patch("pathlib.Path.home", return_value=home):
            return ClaudeAgentViewAdapter().final_text(ASSIGNED, cwd="/work/repo")

    def test_final_message_is_read_from_a_real_transcript(self):
        records = [
            {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "run the phase"}},
            {"type": "assistant", "uuid": "a1", "message": {"id": "m1", "role": "assistant", "stop_reason": "tool_use",
                                                            "content": [{"type": "text", "text": "working"}]}},
            {"type": "assistant", "uuid": "a2", "message": {"id": "m2", "role": "assistant", "stop_reason": "end_turn",
                                                            "content": [{"type": "text", "text": "automation:\n  status: planned"}]}},
        ]
        self.assertEqual(self._run(records), "automation:\n  status: planned")

    def test_an_ambiguous_transcript_yields_nothing(self):
        # An identity-less replay of an earlier answer after a new request is not an
        # answer (agent-harness#1002); the launch then fails closed as transcript_missing.
        old = {"type": "assistant", "message": {"id": "old", "role": "assistant", "stop_reason": "end_turn",
                                                "content": [{"type": "text", "text": "old answer"}]}}
        records = [old, {"type": "user", "uuid": "u2", "message": {"role": "user", "content": "again"}}, old]
        self.assertEqual(self._run(records), "")


class FolderTrustTest(unittest.TestCase):
    """Exact-folder trust preflight, read from the operator's Claude config (never written)."""

    def _config(self, projects):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / ".claude.json"
        path.write_text(json.dumps({"projects": projects}), encoding="utf-8")
        return path

    def test_trusted_exact_folder(self):
        config = self._config({"/work/repo": {"hasTrustDialogAccepted": True}})
        self.assertEqual(workspace_folder_trust(Path("/work/repo"), config_path=config), "trusted")
        state = workspace_trust_state(Path("/work/repo"), config_path=config)
        self.assertEqual((state["status"], state["workspace"]), ("trusted", "trusted"))

    def test_untrusted_folder_blocks_even_with_a_clean_mcp_config(self):
        config = self._config({"/work/repo": {"hasTrustDialogAccepted": False}})
        state = workspace_trust_state(Path("/work/repo"), config_path=config)
        self.assertEqual(state, {"status": "blocked", "workspace": "untrusted", "mcp": "absent"})

    def test_parent_only_trust_does_not_carry_over(self):
        # Observed on the agent-harness#1099 proof: a trusted parent, an untrusted child.
        config = self._config({"/work": {"hasTrustDialogAccepted": True}})
        self.assertEqual(workspace_folder_trust(Path("/work/repo"), config_path=config), "untrusted")

    def test_missing_config_is_unknown_and_blocks(self):
        state = workspace_trust_state(Path("/work/repo"), config_path=Path("/nonexistent/.claude.json"))
        self.assertEqual((state["status"], state["workspace"]), ("blocked", "unknown"))

    def test_config_path_follows_claude_config_dir(self):
        self.assertEqual(claude_global_config_path({"CLAUDE_CONFIG_DIR": "/cfg", "HOME": "/h"}), Path("/cfg/.claude.json"))
        self.assertEqual(claude_global_config_path({"HOME": "/h"}), Path("/h/.claude.json"))

    def test_unknown_trust_refuses_before_any_subprocess_including_the_help_probe(self):
        runner = mock.Mock()
        adapter = ClaudeAgentViewAdapter(runner=runner, config_path=Path("/nonexistent/.claude.json"))
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"):
            lifecycle = adapter.launch_background("do work", cwd="/work/repo", bind_printed_id=True)
        runner.assert_not_called()
        self.assertEqual(lifecycle.blocker.reason, "trust_preflight_blocked")

    def test_untrusted_folder_refuses_before_any_subprocess_with_an_actionable_hint(self):
        config = self._config({"/work": {"hasTrustDialogAccepted": True}})
        runner = mock.Mock()
        adapter = ClaudeAgentViewAdapter(runner=runner, config_path=config)
        with mock.patch("phase_loop_runtime.claude_agent_view.shutil.which", return_value="/usr/bin/claude"):
            lifecycle = adapter.launch_background("do work", cwd="/work/repo", bind_printed_id=True)
        runner.assert_not_called()
        self.assertEqual(lifecycle.blocker.reason, "trust_preflight_blocked")
        self.assertEqual(
            lifecycle.blocker.summary,
            "Workspace /work/repo is not trusted in your Claude settings. Run `claude` in /work/repo once, "
            "accept the trust prompt, then re-run this command.",
        )


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

    def test_fallback_root_follows_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cfg"
            only = config / "projects" / "-some-other-spelling" / f"{ASSIGNED}.jsonl"
            only.parent.mkdir(parents=True)
            only.write_text("{}\n", encoding="utf-8")
            nowhere = lambda cwd: Path(tmp) / "absent"  # noqa: E731
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(config)}):
                self.assertEqual(session_transcript_path(ASSIGNED, cwd="/repo", project_dir_for_cwd=nowhere), only)
            with mock.patch.dict("os.environ", {"HOME": tmp}, clear=False), mock.patch.dict("os.environ", {}, clear=False):
                import os as _os
                _os.environ.pop("CLAUDE_CONFIG_DIR", None)
                with mock.patch("pathlib.Path.home", return_value=Path(tmp)):
                    self.assertIsNone(session_transcript_path(ASSIGNED, cwd="/repo", project_dir_for_cwd=nowhere))


class _ScriptedAdapter(ClaudeAgentViewAdapter):
    def __init__(self, *, launch_state="running", terminal_state="done", text="final", blocker=None, proof=True):
        super().__init__(runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess")))
        self.proof = proof
        self.proof_nonces = []
        self.launch_state = launch_state
        self.terminal_state = terminal_state
        self.text = text
        self.terminal_blocker = blocker
        self.launch_kwargs = None
        self.prompt = None
        self.stopped = []
        self.wait_kwargs = None

    PREEXISTING = frozenset({"99999999-0000-4000-8000-000000000000"})

    def _lifecycle(self, state, blocker=None):
        return AgentViewLifecycleResult(
            session_id="agent-1", state=state, cwd="/repo", logs_ref=None,
            started_at=None, completed_at=None, stop_result=None, blocker=blocker,
            preexisting_session_ids=self.PREEXISTING,
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

    def launch_proof(self, session_id, *, cwd, nonce):
        self.proof_nonces.append(nonce)
        return self.proof

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
        # No permission grants at all (round 4): never --add-dir.
        self.assertNotIn("add_dirs", adapter.launch_kwargs)
        self.assertNotIn("--add-dir", result.command)
        # `--` sits immediately before the prompt, which is last; never a print flag.
        self.assertEqual(result.command[-2], "--")
        self.assertNotIn("-p", result.command)
        self.assertNotIn("--print", result.command)
        # The session is bound by its printed id and the spec's tool policy is carried.
        self.assertTrue(adapter.launch_kwargs["bind_printed_id"])
        self.assertNotIn("--session-id", result.command)
        self.assertEqual(result.command[-2], "--")
        # Never an allow rule, even if a spec carried one (round 1, B1): only the
        # restrictive half of the tool policy reaches the session.
        self.assertNotIn("allowed_tools", adapter.launch_kwargs)
        self.assertNotIn("--allowedTools", result.command)
        self.assertEqual(adapter.launch_kwargs["disallowed_tools"], "AskUserQuestion")
        self.assertEqual(adapter.launch_kwargs["permission"], "bypassPermissions")
        # No deadline unless the operator configured one.
        self.assertIsNone(adapter.wait_kwargs["timeout_s"])
        # Sessions listed before the launch stay excluded while waiting (round 2).
        self.assertEqual(adapter.wait_kwargs["exclude"], _ScriptedAdapter.PREEXISTING)
        self.assertIs(adapter.wait_kwargs["verified"], False)
        self.assertTrue((run_dir / "heartbeat.json").is_file())

    def test_a_binding_verified_at_launch_is_forwarded_to_the_wait(self):
        adapter = _ScriptedAdapter(text="final")
        original = adapter._lifecycle

        def verified_lifecycle(state, blocker=None):
            from dataclasses import replace as _replace
            return _replace(original(state, blocker), binding_verified=True)

        adapter._lifecycle = verified_lifecycle
        self._run(adapter)
        self.assertIs(adapter.wait_kwargs["verified"], True)

    def test_non_bypass_launch_renders_no_permission_mode(self):
        # Round 3 (claude): the converse of B2 at the LAUNCH path, for execute/repair specs
        # built without --bypass-approvals (the spec carries no --permission-mode).
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        adapter = _ScriptedAdapter(text="done")
        spec = LaunchSpec(
            executor="claude",
            command=["claude", "--bg", "--disallowedTools", "AskUserQuestion", "--", "x"],
            prompt_bundle=_PromptBundle(), injection_metadata=None, delivery_mode="agent_view",
            dispatch_decision=None, available=True, selected_model="claude-opus-5-5", selected_effort="high",
            wrapped_cwd=tmp.name, claude_route="claude_agent_view",
        )
        result = _launch_claude_agent_view(spec, log_path=Path(tmp.name) / "run" / "launch.log", adapter=adapter)
        self.assertIsNone(adapter.launch_kwargs["permission"])
        self.assertNotIn("--permission-mode", result.command)
        self.assertEqual(result.command[-2], "--")

    def test_context_outside_the_cwd_is_refused_not_granted(self):
        # Round 4 (maintainer rule): the route adds NO permission grants, so no --add-dir;
        # a context file outside the workspace is refused before any launch.
        cwd = tempfile.TemporaryDirectory()
        runs = tempfile.TemporaryDirectory()
        self.addCleanup(cwd.cleanup)
        self.addCleanup(runs.cleanup)
        adapter = _ScriptedAdapter(text="done")
        spec = LaunchSpec(
            executor="claude", command=["claude", "--bg", "--", "x"], prompt_bundle=_PromptBundle(),
            injection_metadata=None, delivery_mode="agent_view", dispatch_decision=None, available=True,
            selected_model="claude-opus-5-5", selected_effort="high", wrapped_cwd=cwd.name,
            claude_route="claude_agent_view",
        )
        result = _launch_claude_agent_view(spec, log_path=Path(runs.name) / "run" / "launch.log", adapter=adapter)
        self.assertIsNone(adapter.launch_kwargs)          # never launched
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside the launch workspace", result.output)
        self.assertNotIn("--add-dir", result.command)

    def test_the_launch_nonce_is_in_the_prompt_and_checked_before_success(self):
        adapter = _ScriptedAdapter(text="final")
        result, _ = self._run(adapter)
        nonce = adapter.launch_kwargs["launch_nonce"]
        self.assertRegex(nonce, r"^[0-9a-f-]{36}$")
        self.assertTrue(adapter.prompt.endswith(f"phase-loop-launch-nonce: {nonce}"))
        self.assertEqual(result.command[-1], adapter.prompt)
        self.assertEqual(adapter.wait_kwargs["nonce"], nonce)
        self.assertEqual(adapter.proof_nonces, [nonce])
        self.assertEqual(result.returncode, 0)

    def test_a_finished_session_without_the_nonce_is_never_reported(self):
        adapter = _ScriptedAdapter(text="someone else's answer", proof=False)
        result, _ = self._run(adapter)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("someone else's answer", result.output)
        self.assertEqual(result.claude_route_result["status"], "blocked")

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
