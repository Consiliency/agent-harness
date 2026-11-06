"""A fake jailed Claude CLI for the offline ``sdk`` transport tests (SEATS CLAUDE SL-3).

Speaks the stream-json control protocol on stdin/stdout the way the pinned SDK expects:
answers ``initialize``, answers one user message with ``system/init``, one assistant turn
and one successful ``result`` for the ``--session-id=`` it was given, and exits 0 on stdin
EOF. ``FAKE_CLI_MODE`` selects a deviation for a control; ``FAKE_CLI_RECORD`` names a file
that receives the argv, the environment and every stdin line it read.

Never a real CLI: no network, no credential, no file outside the record.
"""

import json
import os
import sys

RESULT_TEXT = "VERDICT: approve\nNo blocking findings."


def emit(value, raw=None):
    sys.stdout.write((raw if raw is not None else json.dumps(value)) + "\n")
    sys.stdout.flush()


def main(argv):
    mode = os.environ.get("FAKE_CLI_MODE", "ok")
    record_path = os.environ.get("FAKE_CLI_RECORD")
    session = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--session-id=")), "")
    model = argv[argv.index("--model") + 1] if "--model" in argv else "claude-unknown"
    seen = []
    for line in sys.stdin:
        seen.append(line.rstrip("\n"))
        message = json.loads(line)
        if message.get("type") == "control_request":
            request = message["request"]
            if mode == "inbound_control_request":
                emit({"type": "control_request", "request_id": "cli_1",
                      "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {}}})
            response = {"subtype": "success", "request_id": message["request_id"],
                        "response": {"commands": [], "models": []}}
            if mode == "uncorrelated_response":
                response["request_id"] = "req_9_deadbeef"
            if request.get("subtype") == "initialize":
                emit({"type": "control_response", "response": response})
            continue
        if message.get("type") != "user":
            continue
        emit({"type": "system", "subtype": "init", "session_id": session,
              "apiKeySource": "ANTHROPIC_API_KEY" if mode == "api_key" else "none",
              "model": model, "tools": [], "mcp_servers": [], "cwd": "/seat/tree",
              "permissionMode": "bypassPermissions"})
        if mode == "transcript_mirror":
            emit({"type": "transcript_mirror", "filePath": "x", "entries": []})
        if mode == "unknown_type":
            emit({"type": "telemetry_ping", "session_id": session})
        if mode == "duplicate_key":
            emit(None, raw='{"type":"assistant","type":"assistant","session_id":"%s"}' % session)
        if mode == "escaped_token":
            token = os.environ.get("FAKE_CLI_TOKEN", "")
            escaped = "".join("\\u%04x" % ord(c) for c in token)
            emit(None, raw='{"type":"assistant","session_id":"%s","message":{"role":"assistant",'
                 '"content":[{"type":"text","text":"%s"}]}}' % (session, escaped))
        emit({"type": "assistant", "session_id": session, "parent_tool_use_id": None,
              "message": {"role": "assistant", "model": model,
                          "content": [{"type": "text", "text": RESULT_TEXT}]}})
        result = {"type": "result", "subtype": "success", "is_error": False,
                  "result": RESULT_TEXT, "session_id": session, "duration_ms": 1,
                  "duration_api_ms": 1, "num_turns": 1, "total_cost_usd": 0.0,
                  "usage": {"input_tokens": 1, "output_tokens": 1}}
        if mode != "no_result":
            emit(result)
        if mode == "second_result":
            emit(result)
    if record_path:
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump({"argv": argv[1:], "env": dict(os.environ), "stdin": seen}, handle,
                      sort_keys=True)
    return 7 if mode == "nonzero_exit" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
