import json
import subprocess
import threading
import unittest
from pathlib import Path

from phase_loop_runtime.claude_channel_sidecar import ChannelSidecar, build_server

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "claude-config" / "plugins" / "phase-loop-channel"
CHANNEL_SCRIPT = PLUGIN_ROOT / "channel" / "phase_loop_channel.py"
SMOKE_SCRIPT = ROOT / "scripts" / "smoke-claude-channel-proof"


class ClaudeChannelMcpTest(unittest.TestCase):
    def test_plugin_manifest_declares_channel_protocol(self):
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

        channels = manifest["components"]["channels"]
        self.assertEqual(channels[0]["protocol"], "experimental.claude/channel")
        self.assertEqual(channels[0]["name"], "phase-loop")

    def test_reply_and_status_schemas_expose_frozen_fields(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("phase_loop_channel", CHANNEL_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        tools = {tool["name"]: tool for tool in module.tool_definitions()}
        self.assertEqual(set(tools), {"reply", "status"})
        expected_fields = {"event_id", "status", "text", "artifacts", "error", "final"}
        for tool in tools.values():
            self.assertEqual(set(tool["inputSchema"]["properties"]), expected_fields)
            self.assertEqual(tool["inputSchema"]["properties"]["status"]["enum"], ["received", "working", "blocked", "done", "error"])

    def test_initialize_declares_channel_capability(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("phase_loop_channel", CHANNEL_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        response = module.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        capabilities = response["result"]["capabilities"]
        self.assertEqual(capabilities["experimental"], {"claude/channel": {}})

    def test_channel_notification_includes_event_id_metadata(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("phase_loop_channel", CHANNEL_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        notification = module.channel_notification(
            {
                "event_id": "evt-1",
                "session_id": "session-a",
                "sender": "phase-loop",
                "content": "channel-ping",
                "ack_policy": "tool_ack_required",
                "created_at": "2026-06-19T00:00:00Z",
                "attachments": [{"ref": "artifact://summary"}],
            }
        )

        self.assertEqual(notification["method"], "notifications/claude/channel")
        self.assertIn('event_id="evt-1"', notification["params"]["content"])
        self.assertEqual(notification["params"]["meta"]["event_id"], "evt-1")

    def test_tool_calls_forward_to_sidecar_ack_state(self):
        import importlib.util

        sidecar = ChannelSidecar()
        event = sidecar.create_message("session-a", sender="phase-loop", content="channel-ping")
        server = build_server("127.0.0.1", 0, sidecar)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            spec = importlib.util.spec_from_file_location("phase_loop_channel", CHANNEL_SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            state = module.forward_tool_call(
                "reply",
                {"event_id": event.event_id, "status": "done", "text": "pong", "artifacts": [{"ref": "artifact://reply"}], "final": True},
                endpoint=f"http://127.0.0.1:{server.server_port}",
                session_id="session-a",
            )
            self.assertTrue(state["acknowledged"])
            self.assertEqual(state["event_id"], event.event_id)
        finally:
            server.shutdown()
            server.server_close()

    def test_smoke_dry_run_rejects_print_bare_command_templates(self):
        text = SMOKE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("FORBIDDEN_COMMAND_TOKENS", text)
        self.assertNotIn('"claude", "-p"', text)
        self.assertIn("pty.openpty", text)
        self.assertNotIn('"--print"', json.dumps(json.loads(subprocess.check_output([str(SMOKE_SCRIPT), "--dry-run"], text=True))["command"]))
        self.assertNotIn('"--bare"', json.dumps(json.loads(subprocess.check_output([str(SMOKE_SCRIPT), "--dry-run"], text=True))["command"]))


if __name__ == "__main__":
    unittest.main()
