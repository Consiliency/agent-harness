"""The ``sdk`` transport's host worker session (SEATS CLAUDE SL-3).

Loaded by ``claude_sdk_bootstrap`` after the filter, closure and import checks, never as a
script. It reports readiness (liveness only, never authority), checks the frozen timer
values it was launched with, runs one adapter session and reports one closed outcome.

The worker holds only the sealed prompt, the frozen public configuration and the frames
the parent approved. It writes no file, opens no socket and starts no process; nothing it
says confers launch, credential or admission authority.
"""

import os
import re

#: The frozen SDK timer variables. The launcher sets each from the launch fixture and the
#: parent sends the same values in its hello; a mismatch or a malformed value refuses.
TIMER_ENV = ("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS")
_TIMER_RE = re.compile(r"[1-9][0-9]{0,8}")


def _timers_valid(expected):
    if not isinstance(expected, dict) or set(expected) != set(TIMER_ENV):
        return False
    for name in TIMER_ENV:
        value = expected[name]
        if not isinstance(value, str) or not _TIMER_RE.fullmatch(value):
            return False
        if os.environ.get(name) != value:
            return False
    return True


def _code_of(exc):
    """The first closed code in an exception or exception group, else ``session_failed``."""
    pending = [exc]
    while pending:
        current = pending.pop(0)
        code = getattr(current, "code", None)
        if isinstance(code, str):
            return code
        children = getattr(current, "exceptions", None)  # an exception group's members
        if isinstance(children, tuple):
            pending.extend(children)
    return "session_failed"


def _silence(*_args):
    return None


def run(channel, hello):
    """One session. Returns the process exit status (0 only for a completed session)."""
    import sys
    import threading

    # No traceback, warning or unraisable report is ever written by the worker.
    sys.excepthook = _silence
    sys.unraisablehook = _silence
    threading.excepthook = _silence
    if not _timers_valid(hello.get("timers")):
        channel.fail("timer_invalid")
        return 3
    try:
        import claude_sdk_adapter
    except ImportError:
        channel.fail("dependency_missing")
        return 3
    channel.send("ready", {})
    try:
        outcome = claude_sdk_adapter.run_session(channel, hello)
    except BaseException as exc:  # reduced to one closed code; no text leaves the worker
        channel.fail(_code_of(exc))
        return 3
    channel.send("done", {"outcome": outcome})
    channel.closed = True
    return 0
