"""SEATS CLAUDE SL-3: the seat-neutral SDK adapter's own controls (EC-CLAUDE-3).

The adapter is loaded from the packaged worker payload by path, as the worker loads it,
against this environment's pinned SDK (a test oracle: the worker itself runs from its own
sealed install). Covered: the field-by-field option freeze, the transport and client
construction rules (no stock transport, no solo route), the transport lifecycle and its
bounds, a whole in-process session against a scripted parent, and the forbidden calls.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import dataclasses
import importlib.util
import json
import logging
import queue
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import claude_seat_sdk as sdk

PAYLOAD = Path(sdk.__file__).resolve().parent / "data" / "claude_sdk" / "worker"
ADAPTER_SOURCE = PAYLOAD / "claude_sdk_adapter.py"
FIXTURE = json.loads(sdk.read_packaged(sdk.LAUNCH_FIXTURE))
SESSION = "11111111-2222-4333-8444-555555555555"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PAYLOAD / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def adapter():
    saved = (logging.root.manager.disable, logging.lastResort, logging.raiseExceptions)
    bootstrap = _load("claude_sdk_bootstrap")
    sys.modules.setdefault("claude_sdk_bootstrap", bootstrap)
    module = _load("claude_sdk_adapter")
    disabled = logging.root.manager.disable
    logging.disable(saved[0])
    logging.lastResort, logging.raiseExceptions = saved[1], saved[2]
    module._observed_disable = disabled
    module._bootstrap = bootstrap
    return module


def options_values() -> dict:
    return sdk.frozen_options(model="claude-model-under-test", effort="high",
                              session_id=SESSION, settings='{"apiKeyHelper": ""}',
                              fixture=FIXTURE)


class FakeChannel:
    """The worker channel, with a scripted parent behind it: each frame the adapter sends
    may queue the parent's answers, which ``read`` hands back in order."""

    def __init__(self, script=None):
        self.sent: list[tuple[str, object]] = []
        self.inbox: queue.Queue = queue.Queue()
        self.script = script or (lambda channel, kind, body: None)
        self.parse = staticmethod(_load("claude_sdk_bootstrap").parse_frame)

    def push(self, kind, body=None):
        self.inbox.put((kind, {} if body is None else body))

    def read(self):
        item = self.inbox.get(timeout=60)
        return None if item == "EOF" else item

    def send(self, kind, body):
        self.sent.append((kind, copy.deepcopy(body)))
        self.script(self, kind, body)


def _parent(channel, kind, body):
    """A well-behaved parent: answers initialize, then the envelope, then ends."""
    if kind == "cli" and body.get("type") == "control_request":
        channel.push("cli", {"type": "control_response", "response": {
            "subtype": "success", "request_id": body["request_id"], "response": {}}})
    elif kind == "end_input":
        for frame in (
            {"type": "system", "subtype": "init", "session_id": SESSION, "apiKeySource": "none"},
            {"type": "assistant", "session_id": SESSION, "parent_tool_use_id": None,
             "message": {"role": "assistant", "model": "m",
                         "content": [{"type": "text", "text": "VERDICT: ok"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "VERDICT: ok",
             "session_id": SESSION, "duration_ms": 1, "duration_api_ms": 1, "num_turns": 1,
             "total_cost_usd": 0.0, "usage": {}},
        ):
            channel.push("cli", frame)
        channel.push("eof")


# --------------------------------------------------------------------------------------
# The option freeze.
# --------------------------------------------------------------------------------------

def test_the_freeze_is_the_fixture_and_names_every_field(adapter):
    options = adapter.frozen_options(options_values())
    assert type(options).__name__ == "ClaudeAgentOptions"
    assert set(options_values()) == set(adapter.option_fields())
    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}
    assert options.hooks is None and options.can_use_tool is None and options.mcp_servers == {}


def test_a_missing_or_extra_option_field_refuses(adapter):
    values = options_values()
    values.pop("hooks")
    with pytest.raises(adapter.AdapterRefused):
        adapter.frozen_options(values)
    values = options_values()
    values["future_field"] = None
    with pytest.raises(adapter.AdapterRefused):
        adapter.frozen_options(values)


_ENABLED = {
    "session_store": {"x": 1}, "resume": "abc", "continue_conversation": True,
    "plugins": [{"type": "local", "path": "/x"}], "skills": ["s"], "env": {"A": "1"},
    "agents": {"a": {}}, "hooks": {"PreToolUse": []}, "mcp_servers": {"s": {}},
    "add_dirs": ["/"], "extra_args": {"bare": None}, "cli_path": "/usr/bin/claude",
    "include_partial_messages": True, "enable_file_checkpointing": True, "fork_session": True,
    "verbatim_prompts": True, "allowed_tools": ["Bash"], "permission_prompt_tool_name": "x",
}


@pytest.mark.parametrize("field", sorted(_ENABLED))
def test_an_enabled_forbidden_option_refuses(adapter, field):
    values = options_values()
    values[field] = _ENABLED[field]
    with pytest.raises(adapter.AdapterRefused):
        adapter.frozen_options(values)


@pytest.mark.parametrize("field, value", [
    ("system_prompt", {"type": "preset", "preset": "claude_code", "append": "x"}),
    ("system_prompt", None), ("permission_mode", "default"), ("setting_sources", ["user"]),
    ("strict_mcp_config", False), ("tools", []),
])
def test_a_changed_required_option_refuses(adapter, field, value):
    values = options_values()
    values[field] = value
    with pytest.raises(adapter.AdapterRefused):
        adapter.frozen_options(values)


def test_a_constructed_options_object_is_held_to_the_same_freeze(adapter):
    options = adapter.frozen_options(options_values())
    changed = dataclasses.replace(options, hooks={"Stop": []})
    with pytest.raises(adapter.AdapterRefused):
        adapter.check_options(changed)


# --------------------------------------------------------------------------------------
# The client and transport construction rules.
# --------------------------------------------------------------------------------------

def test_the_client_takes_only_the_ipc_transport(adapter):
    from claude_agent_sdk._internal.transport import subprocess_cli

    options = adapter.frozen_options(options_values())
    loop = asyncio.new_event_loop()
    try:
        transport = adapter.IPCTransport(FakeChannel(), loop)
        assert type(adapter.build_client(options, transport)).__name__ == "ClaudeSDKClient"

        class Sub(adapter.IPCTransport):
            pass

        stock = subprocess_cli.SubprocessCLITransport(prompt="", options=options)
        for other in (None, stock, Sub(FakeChannel(), loop)):
            with pytest.raises(adapter.AdapterRefused):
                adapter.build_client(options, other)
    finally:
        loop.close()


def test_the_adapter_has_no_route_of_its_own():
    tree = ast.parse(ADAPTER_SOURCE.read_bytes())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module}.{a.name}" for a in node.names)
            imported.add(node.module or "")
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            assert name not in ("SubprocessCLITransport", "get_server_info", "system", "popen",
                                "execv", "fork", "create_subprocess_exec"), name
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            raise AssertionError("the adapter has a script entry point")
    assert not {"subprocess", "socket", "multiprocessing", "pty"} & imported
    assert not any(n.startswith("claude_agent_sdk._internal.transport") for n in imported)
    assert "claude_agent_sdk.query" not in imported


def test_importing_the_adapter_silences_logging(adapter):
    assert adapter._observed_disable >= logging.CRITICAL


# --------------------------------------------------------------------------------------
# The transport lifecycle.
# --------------------------------------------------------------------------------------

def _transport(adapter, channel):
    loop = asyncio.new_event_loop()
    transport = adapter.IPCTransport(channel, loop)
    return loop, transport


def _started(adapter, channel):
    loop, transport = _transport(adapter, channel)
    started = asyncio.Event()
    import threading

    channel.push("start")
    thread = threading.Thread(target=transport.pump, args=(started,), daemon=True)
    thread.start()
    loop.run_until_complete(asyncio.wait_for(started.wait(), 30))
    return loop, transport, thread


def test_connect_before_the_parent_starts_the_leg_refuses(adapter):
    loop, transport = _transport(adapter, FakeChannel())
    try:
        with pytest.raises(adapter.AdapterRefused):
            loop.run_until_complete(transport.connect())
    finally:
        loop.close()


def test_writes_are_parsed_objects_and_end_input_is_single(adapter):
    channel = FakeChannel()
    loop, transport, _thread = _started(adapter, channel)
    try:
        loop.run_until_complete(transport.connect())
        loop.run_until_complete(transport.write('{"type": "user", "x": "\\u0041"}\n'))
        assert channel.sent[-1] == ("cli", {"type": "user", "x": "A"})
        for bad in ('{"a": 1, "a": 2}\n', "not json\n", '["list"]\n', '{"a": 1}\n{"b": 2}\n'):
            with pytest.raises(adapter.AdapterRefused):
                loop.run_until_complete(transport.write(bad))
        loop.run_until_complete(transport.end_input())
        assert channel.sent[-1] == ("end_input", {})
        with pytest.raises(adapter.AdapterRefused):
            loop.run_until_complete(transport.end_input())
        with pytest.raises(adapter.AdapterRefused):
            loop.run_until_complete(transport.write('{"type": "user"}\n'))
        loop.run_until_complete(asyncio.wait_for(transport.close(), 1))
        assert not transport.is_ready()
    finally:
        channel.push("eof")
        loop.close()


async def _drain(transport):
    return [item async for item in transport.read_messages()]


def test_reads_yield_parent_frames_in_order_and_stop_at_eof(adapter):
    channel = FakeChannel()
    loop, transport, thread = _started(adapter, channel)
    try:
        channel.push("cli", {"type": "system", "n": 1})
        channel.push("cli", {"type": "assistant", "n": 2})
        channel.push("eof")
        assert loop.run_until_complete(asyncio.wait_for(_drain(transport), 30)) == [
            {"type": "system", "n": 1}, {"type": "assistant", "n": 2}]
        thread.join(5)
    finally:
        loop.close()


@pytest.mark.parametrize("kind, body", [("hello", {}), ("cli", ["x"]), ("eof", {"x": 1}),
                                        ("start", {})])
def test_an_unexpected_parent_frame_ends_the_session_typed(adapter, kind, body):
    channel = FakeChannel()
    loop, transport, thread = _started(adapter, channel)
    try:
        channel.push(kind, body)
        with pytest.raises(adapter.AdapterRefused):
            loop.run_until_complete(asyncio.wait_for(_drain(transport), 30))
    finally:
        loop.close()


def test_the_frame_queue_is_bounded(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "QUEUE_CAP", 3)
    channel = FakeChannel()
    loop, transport, thread = _started(adapter, channel)
    try:
        for n in range(6):
            channel.push("cli", {"type": "system", "n": n})
        channel.push("eof")
        thread.join(10)
        with pytest.raises(adapter.AdapterRefused):
            loop.run_until_complete(asyncio.wait_for(_drain(transport), 30))
    finally:
        loop.close()


# --------------------------------------------------------------------------------------
# A whole session, in process, against the scripted parent.
# --------------------------------------------------------------------------------------

def test_a_whole_session_sends_exactly_the_frozen_sequence(adapter, monkeypatch):
    from claude_agent_sdk import ClaudeSDKClient
    from claude_agent_sdk._internal.transport import subprocess_cli

    def forbidden(*_a, **_k):
        raise AssertionError("a forbidden SDK call")

    monkeypatch.setattr(subprocess_cli.SubprocessCLITransport, "__init__", forbidden)
    monkeypatch.setattr(ClaudeSDKClient, "get_server_info", forbidden)
    channel = FakeChannel(_parent)
    channel.push("start")
    outcome = adapter.run_session(channel, {"options": options_values(),
                                            "prompt": "the sealed prompt"})
    assert outcome == "result"
    kinds = [kind for kind, _body in channel.sent]
    assert kinds == ["cli", "cli", "end_input"]
    init, user = channel.sent[0][1], channel.sent[1][1]
    assert init == {**FIXTURE["protocol"]["outbound"]["initialize"],
                    "request_id": init["request_id"]}
    assert user == {**FIXTURE["protocol"]["outbound"]["user"],
                    "message": {"role": "user", "content": "the sealed prompt"}}


def test_a_session_without_a_result_reports_no_result(adapter):
    def parent(channel, kind, body):
        if kind == "cli" and body.get("type") == "control_request":
            _parent(channel, kind, body)
        elif kind == "end_input":
            channel.push("eof")

    channel = FakeChannel(parent)
    channel.push("start")
    assert adapter.run_session(channel, {"options": options_values(), "prompt": "p"}) == "no_result"


@pytest.mark.parametrize("label", ["empty options", "no options", "no prompt", "empty prompt"])
def test_a_malformed_hello_refuses_before_any_frame(adapter, label):
    hello = {
        "empty options": {"options": {}, "prompt": "p"},
        "no options": {"prompt": "p"},
        "no prompt": {"options": options_values()},
        "empty prompt": {"options": options_values(), "prompt": ""},
    }[label]
    channel = FakeChannel(_parent)
    channel.push("start")
    with pytest.raises(adapter.AdapterRefused):
        adapter.run_session(channel, hello)
    assert channel.sent == []


def test_the_pinned_sdk_is_the_one_imported(adapter):
    from claude_agent_sdk._version import __version__

    assert __version__ == adapter.SDK_VERSION == sdk.SDK_VERSION
