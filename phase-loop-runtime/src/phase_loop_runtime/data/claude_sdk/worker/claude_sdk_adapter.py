"""The seat-neutral Claude Agent SDK adapter (SEATS CLAUDE SL-3).

Runs only inside the host worker, after ``claude_sdk_bootstrap`` verified the closure. It
selects a custom :class:`IPCTransport` for ``ClaudeSDKClient`` before connecting, so the SDK
never builds a command, spawns a process, reads a session store or materializes a
credential: every CLI-bound object goes to the parent over the worker's channel, and every
CLI frame the SDK sees is one the parent parsed and approved first.

The adapter has no route of its own. It never constructs or subclasses the SDK's stock
subprocess transport, never names a CLI path, never calls ``get_server_info``, and refuses
options that would enable sessions, plugins, skills, agents, hooks, tool callbacks, SDK MCP
servers, extra environment or stderr callbacks. SDK logging is disabled, and any failure
reaches the parent as one closed code, never as exception text.
"""

import asyncio
import collections
import dataclasses
import json
import logging
import threading

# No SDK record, warning or last-resort line is ever written, before or after import.
logging.disable(logging.CRITICAL)
logging.lastResort = None
logging.raiseExceptions = False

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, Transport  # noqa: E402
from claude_agent_sdk._version import __version__ as _SDK_VERSION  # noqa: E402

SDK_VERSION = "0.2.167"
#: Option fields that must keep exactly these values.
REQUIRED = {
    "system_prompt": {"type": "preset", "preset": "claude_code"},
    "tools": {"type": "preset", "preset": "claude_code"},
    "permission_mode": "bypassPermissions",
    "setting_sources": [],
    "strict_mcp_config": True,
}
#: Option fields that must be absent (``None``), false or empty.
EMPTY = (
    "session_store", "resume", "continue_conversation", "plugins", "skills", "stderr", "env",
    "agents", "can_use_tool", "hooks", "mcp_servers", "add_dirs", "extra_args", "sandbox",
    "user", "fork_session", "resume_session_at", "resume_drops_turn", "cli_path", "cwd",
    "enable_file_checkpointing", "include_hook_events", "include_partial_messages",
    "forward_subagent_text", "verbatim_prompts", "output_format",
    "permission_prompt_tool_name", "allowed_tools", "disallowed_tools", "betas",
    "fallback_model", "max_turns", "max_budget_usd", "task_budget", "thinking",
    "max_thinking_tokens", "max_buffer_size", "debug_stderr",
)
#: The parsed CLI frames the worker can hold before the SDK reads them.
QUEUE_CAP = 4096
FRAME_CAP_BYTES = 16 << 20
_EOF = object()


class AdapterRefused(Exception):
    def __init__(self, code="protocol_violation"):
        super().__init__(code)
        self.code = code


def option_fields():
    return tuple(field.name for field in dataclasses.fields(ClaudeAgentOptions))


def frozen_options(values):
    """``ClaudeAgentOptions`` from the frozen configuration, field by field. The mapping
    must name every field of the pinned SDK and no other; :data:`REQUIRED` and
    :data:`EMPTY` hold whatever it says."""
    if _SDK_VERSION != SDK_VERSION or not isinstance(values, dict):
        raise AdapterRefused("dependency_missing")
    if set(values) != set(option_fields()):
        raise AdapterRefused("protocol_violation")
    for name, value in REQUIRED.items():
        if values[name] != value:
            raise AdapterRefused("protocol_violation")
    for name in EMPTY:
        if values[name] not in (None, False, [], {}):
            raise AdapterRefused("protocol_violation")
    options = ClaudeAgentOptions(**{name: _copy(value) for name, value in values.items()})
    check_options(options)
    return options


def _copy(value):
    return json.loads(json.dumps(value))


def check_options(options):
    """The same freeze on a constructed object (a caller may hand one in directly)."""
    if type(options) is not ClaudeAgentOptions:
        raise AdapterRefused("protocol_violation")
    for name, value in REQUIRED.items():
        if getattr(options, name) != value:
            raise AdapterRefused("protocol_violation")
    for name in EMPTY:
        if getattr(options, name) not in (None, False, [], {}):
            raise AdapterRefused("protocol_violation")


def build_client(options, transport):
    """The only client constructor: the exact :class:`IPCTransport`, never ``None`` (which
    would select the stock transport) and never any other transport object."""
    if type(transport) is not IPCTransport:
        raise AdapterRefused("protocol_violation")
    check_options(options)
    return ClaudeSDKClient(options=options, transport=transport)


def _strict_object(channel, data):
    """One SDK-written line, parsed under the channel's own frame rules."""
    raw = data.encode("utf-8", errors="strict") if isinstance(data, str) else None
    if raw is None or len(raw) > FRAME_CAP_BYTES:
        raise AdapterRefused("protocol_violation")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if b"\n" in raw or not raw.strip():
        raise AdapterRefused("protocol_violation")
    try:
        return channel.parse(raw)
    except Exception:
        raise AdapterRefused("protocol_violation") from None


class IPCTransport(Transport):
    """The SDK's transport over the worker channel. ``connect`` is a no-op once the parent
    has started the leg; ``write`` sends one parsed object; ``end_input`` sends the single
    end-of-input signal, on which the parent closes the CLI's stdin; ``read_messages``
    yields only parent-approved objects; ``close`` never awaits."""

    def __init__(self, channel, loop):
        self._channel = channel
        self._loop = loop
        self._items = collections.deque()
        self._arrived = asyncio.Event()
        self._started = False
        self._ended = False
        self._closed = False
        self._overflow = False
        self._violation = None

    # -- the reader thread's side --------------------------------------------------

    def _deliver(self, item):
        # Runs on the event loop (``call_soon_threadsafe``), never on the reader thread.
        if len(self._items) >= QUEUE_CAP:
            self._overflow = True
            self._items.clear()
            self._items.append(_EOF)
        else:
            self._items.append(item)
        self._arrived.set()

    def pump(self, started):
        """Read parent frames until EOF. The first must be ``start``; after it only ``cli``
        objects, one ``eof`` and ``cancel`` are accepted."""
        try:
            first = self._channel.read()
            if first is None or first[0] != "start" or first[1] != {}:
                raise AdapterRefused("protocol_violation")
            self._started = True
            self._post(started.set)
            while True:
                frame = self._channel.read()
                if frame is None:
                    break
                kind, body = frame
                if kind == "cli" and isinstance(body, dict):
                    self._post(self._deliver, body)
                elif kind in ("eof", "cancel") and body == {}:
                    break
                else:
                    raise AdapterRefused("protocol_violation")
        except Exception as exc:
            self._violation = getattr(exc, "code", "protocol_violation")
            self._post(started.set)
        self._post(self._deliver, _EOF)

    def _post(self, callback, *args):
        try:
            self._loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            pass  # the session already ended and closed its loop

    # -- the SDK's side ------------------------------------------------------------

    def _check(self):
        if self._violation is not None or self._overflow:
            raise AdapterRefused(self._violation or "protocol_violation")

    async def connect(self):
        self._check()
        if not self._started or self._closed:
            raise AdapterRefused("protocol_violation")

    async def write(self, data):
        self._check()
        if self._closed or self._ended:
            raise AdapterRefused("protocol_violation")
        self._channel.send("cli", _strict_object(self._channel, data))

    async def end_input(self):
        self._check()
        if self._closed or self._ended:
            raise AdapterRefused("protocol_violation")
        self._ended = True
        self._channel.send("end_input", {})

    def read_messages(self):
        return self._messages()

    async def _messages(self):
        while True:
            while not self._items:
                self._arrived.clear()
                await self._arrived.wait()
            item = self._items.popleft()
            self._check()
            if item is _EOF:
                return
            yield item

    async def close(self):
        self._closed = True

    def is_ready(self):
        return self._started and not self._closed and self._violation is None


async def _session(channel, hello):
    loop = asyncio.get_running_loop()
    options = frozen_options(hello.get("options"))
    prompt = hello.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise AdapterRefused("protocol_violation")
    transport = IPCTransport(channel, loop)
    started = asyncio.Event()
    reader = threading.Thread(target=transport.pump, args=(started,), daemon=True,
                              name="claude-sdk-ipc")
    reader.start()
    await started.wait()
    transport._check()
    client = build_client(options, transport)
    seen = False
    try:
        await client.connect()
        await client.query(prompt)
        await transport.end_input()
        messages = client.receive_messages()
        try:
            async for message in messages:
                if isinstance(message, ResultMessage):
                    seen = True
                    break
        finally:
            await messages.aclose()
        transport._check()
    finally:
        await client.disconnect()
    return "result" if seen else "no_result"


def _silence(loop, context):
    return None


def run_session(channel, hello):
    """One SDK session over ``channel``. The returned outcome (``result`` or
    ``no_result``) is liveness only; the parent's admission decides the leg."""
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_silence)
    try:
        return loop.run_until_complete(_session(channel, hello))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
