import json
import subprocess
import unittest

from phase_loop_runtime.claude_agent_view import ClaudeAgentViewAdapter


class ClaudeAgentViewAdapterTest(unittest.TestCase):
    def test_lists_sessions_as_non_secret_metadata(self):
        payload = [
            {
                "id": "agent-1",
                "session_id": "session-1",
                "cwd": "/repo",
                "kind": "background",
                "state": "running",
                "status": "active",
                "name": "BG",
                "started_at": "2026-06-19T12:00:00Z",
                "pid": 123,
                "token": "secret",
                "logs": "raw transcript",
                "provider_payload": {"api_key": "secret"},
            },
            {"id": "agent-2", "status": "completed"},
        ]
        adapter = ClaudeAgentViewAdapter(runner=_runner(stdout=json.dumps(payload)))

        result = adapter.list_sessions(cwd="/repo")

        self.assertTrue(result.ok)
        self.assertEqual(tuple(result.command), ("claude", "agents", "--json", "--all"))
        self.assertEqual(result.sessions[0].state, "running")
        self.assertEqual(result.sessions[1].state, "done")
        rendered = json.dumps(result.to_json(), sort_keys=True)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("raw transcript", rendered)
        self.assertNotIn("provider_payload", rendered)

    def test_command_builders_preserve_launch_options_without_invoking_claude(self):
        adapter = ClaudeAgentViewAdapter()

        self.assertEqual(adapter.list_command(), ["claude", "agents", "--json", "--all"])
        self.assertEqual(adapter.logs_command("agent-1"), ["claude", "logs", "agent-1"])
        self.assertEqual(adapter.attach_command("agent-1"), ["claude", "attach", "agent-1"])
        self.assertEqual(adapter.stop_command("agent-1"), ["claude", "stop", "agent-1"])
        self.assertEqual(adapter.remove_command("agent-1"), ["claude", "rm", "agent-1"])
        self.assertEqual(
            adapter.launch_command(
                "do work",
                cwd="/repo",
                name="c2-bg-test",
                model="sonnet",
                effort="high",
                permission="plan",
                plugin_dirs=["/plugins/a"],
                settings="/settings.json",
                mcp_config="/mcp.json",
                add_dirs=["/repo/docs", "/repo/vendor"],
            ),
            [
                "claude",
                "--bg",
                "--name",
                "c2-bg-test",
                "--cwd",
                "/repo",
                "--model",
                "sonnet",
                "--effort",
                "high",
                "--permission-mode",
                "plan",
                "--plugin-dir",
                "/plugins/a",
                "--settings",
                "/settings.json",
                "--mcp-config",
                "/mcp.json",
                "--add-dir",
                "/repo/docs",
                "--add-dir",
                "/repo/vendor",
                "do work",
            ],
        )

    def test_malformed_list_output_blocks_without_crashing(self):
        adapter = ClaudeAgentViewAdapter(runner=_runner(stdout="not json"))

        result = adapter.list_sessions()

        self.assertFalse(result.ok)
        self.assertEqual(result.sessions, ())
        self.assertEqual(result.blocker.reason, "agents_list_non_json")

    def test_unknown_state_reduces_to_unknown_metadata(self):
        adapter = ClaudeAgentViewAdapter(runner=_runner(stdout=json.dumps([{"id": "agent-1", "state": "new-state"}])))

        result = adapter.list_sessions()

        self.assertTrue(result.ok)
        self.assertEqual(result.sessions[0].state, "unknown")


def _runner(*, stdout, returncode=0):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, returncode, stdout=stdout)

    return run


if __name__ == "__main__":
    unittest.main()
