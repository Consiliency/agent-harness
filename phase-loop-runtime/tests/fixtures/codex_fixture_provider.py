"""Scripted Responses fixture for the real Codex CLI; no external upstream."""
import json
import threading

from test_seat_egress_allowlist_codex import FixtureUpstream, _ACCOUNTS_CHECK_REPLY


def response_events(item, *, index=0):
    response = {"id": "resp_fixture", "status": "completed", "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    events = [
        ("response.created", {"response": {"id": "resp_fixture", "status": "in_progress"}}),
        ("response.output_item.added", {"output_index": index, "item": item}),
        ("response.output_item.done", {"output_index": index, "item": item}),
        ("response.completed", {"response": response}),
    ]
    return b"".join((f"event: {name}\ndata: " + json.dumps({"type": name, **body}) + "\n\n").encode()
                    for name, body in events)


def scripted_call(document, command):
    tools = document.get("tools", [])
    names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    if "shell_command" in names:
        name, arguments = "shell_command", {"command": command}
    elif "exec_command" in names:
        name, arguments = "exec_command", {"cmd": command}
    elif "shell" in names:
        name, arguments = "shell", {"command": ["/bin/sh", "-c", command]}
    else:
        raise ValueError("fixture shell tool unavailable")
    return {"id": "fc_fixture", "type": "function_call", "name": name,
            "call_id": "call_fixture", "arguments": json.dumps(arguments)}


class CodexFixtureProvider(FixtureUpstream):
    def __init__(self, directory, hosts, *, command="cat /seat/tree/SENTINEL", silence_s=0):
        self.command = command
        self.bodies = []
        self.tool_outputs = []
        self.problems = []
        self._local = threading.local()
        super().__init__(directory, hosts, silence_s=silence_s)

    def _drain_body(self, tls, headers, rest):
        if headers.get("transfer-encoding", "").lower() == "chunked":
            while not rest.endswith(b"0\r\n\r\n") and len(rest) < 1 << 24:
                chunk = tls.recv(65536)
                if not chunk:
                    raise OSError("truncated fixture body")
                rest += chunk
            body = b""
            while True:
                size, _, rest = rest.partition(b"\r\n")
                length = int(size.split(b";", 1)[0], 16)
                if not length:
                    break
                body += rest[:length]
                rest = rest[length + 2:]
        else:
            length = int(headers.get("content-length", "0"))
            while len(rest) < length:
                chunk = tls.recv(min(65536, length - len(rest)))
                if not chunk:
                    raise OSError("truncated fixture body")
                rest += chunk
            body = rest[:length]
        self._local.body = body

    def _respond(self, tls, method, target):
        if method == "GET" and "/accounts/check" in target:
            self._reply(tls, 200, "application/json", _ACCOUNTS_CHECK_REPLY)
            return
        if method != "POST" or "/responses" not in target:
            self._reply(tls, 404, "application/json", b"{}")
            return
        body = self._local.body
        with self._lock:
            self.bodies.append(body)
        try:
            document = json.loads(body)
            outputs = [item for item in document.get("input", [])
                       if isinstance(item, dict) and item.get("type") == "function_call_output"]
            if not outputs:
                item = scripted_call(document, self.command)
            else:
                with self._lock:
                    self.tool_outputs.extend(outputs)
                item = {"id": "msg_fixture", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text", "text": "Fixture complete.\n\nAGREE"}]}
            self._reply(tls, 200, "text/event-stream", response_events(item))
        except (ValueError, TypeError) as exc:
            with self._lock:
                self.problems.append(str(exc))
            self._reply(tls, 404, "application/json", b"{}")


FIXTURE_CONFIG = (
    "-c", 'model_provider="seat_fixture"',
    "-c", 'model_providers.seat_fixture.name="Seat fixture"',
    "-c", 'model_providers.seat_fixture.base_url="https://chatgpt.com/backend-api/codex"',
    "-c", 'model_providers.seat_fixture.wire_api="responses"',
    "-c", "model_providers.seat_fixture.requires_openai_auth=true",
    "-c", "model_providers.seat_fixture.request_max_retries=0",
    "-c", "model_providers.seat_fixture.stream_max_retries=0",
)
