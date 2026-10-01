"""Launch ownership preserves the existing tool-permission defaults."""

import json

from phase_loop_runtime import panel_invoker


def test_workspace_tui_review_preserves_its_tool_permissions(tmp_path):
    review = tmp_path / "review"
    review.mkdir()
    command = panel_invoker._claude_tui_command(review, tmp_path)
    assert command[command.index("--permission-mode") + 1] == "default"
    assert "--allow-dangerously-skip-permissions" not in command
    assert "--dangerously-skip-permissions" not in command
    tools = set(command[command.index("--tools") + 1].split(","))
    assert tools == {"Read", "Write"}
    assert command[command.index("--allowedTools") + 1] == command[command.index("--tools") + 1]
    assert command[command.index("--setting-sources") + 1] == ""
    assert json.loads(command[command.index("--mcp-config") + 1]) == {"mcpServers": {}}


def test_broker_only_tui_does_not_gain_workspace_tools():
    command = panel_invoker._broker_claude_tui_command(
        model=None, effort=None, session_id="synthetic-session",
    )
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--allowedTools") + 1] == ""
