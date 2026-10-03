"""Runtime completeness check for agent-CLI scratch decisions (agent-harness#1147).

A static scan of Python cannot be complete: every round of review found another spelling
of a launch (``getattr``, ``functools.partial``, an argv built elsewhere, a runner passed
as a value). This hook does not read source. It watches the interpreter's own audit
events for every process spawn -- ``subprocess.Popen``, ``os.exec*``, ``os.posix_spawn*``,
``os.spawn*``, ``os.system``, ``pty.spawn`` -- and, when the PROGRAM or any argv word
resolves to an agent CLI (after ``env`` / shell ``-c`` parsing), requires the spawn's env
to carry ``sandbox_policy.CHILD_SCRATCH_MARKER``, which only the scratch decision
(``child_scratch_env``) stamps. A launch path that skips the decision therefore fails
whatever test exercises it, however it is spelled.

Only spawns made BY THE RUNTIME are judged: the first frame outside the standard library
must be inside the ``phase_loop_runtime`` package. Test code that starts its own fake
CLIs is not a runtime launch.

Violations are recorded, never raised into the spawning code (which may catch and
degrade), and ``conftest.py`` fails the test that produced one at teardown.
"""

from __future__ import annotations

import os
import shlex
import sys
import sysconfig
from pathlib import Path

#: Agent CLI program names, including their npm package basenames.
AGENT_CLIS = frozenset({"claude", "codex", "gemini", "agy", "grok", "cursor-agent", "opencode",
                        "claude-code", "gemini-cli"})
MARKER = "PHASE_LOOP_SCRATCH_DECIDED"

#: Directories whose code counts as the runtime. Tests may add one (a falsifier module).
RUNTIME_ROOTS = [str(Path(__file__).resolve().parents[1] / "src" / "phase_loop_runtime") + os.sep]
_STDLIB = tuple(
    str(Path(p).resolve()) + os.sep
    for p in {sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"]}
)
_HOOK_FILE = str(Path(__file__).resolve())

violations: list[str] = []
enabled = False
#: Also appended here, so a spawn in a FORKED child (which inherits this hook but not the
#: parent's list) is still reported. Set by conftest.
log_path: str | None = None


def _words(value: object) -> list[str]:
    """Every word of one argv element, with shell quoting resolved and metacharacters
    separating words (``sh -c "cd x; claude -p"`` yields ``claude``)."""
    text = os.fsdecode(value) if isinstance(value, (bytes, os.PathLike)) else str(value)
    for meta in ";&|()<>`":
        text = text.replace(meta, " ")
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})


def _text(value: object) -> str:
    return os.fsdecode(value) if isinstance(value, (bytes, os.PathLike)) else str(value)


def agent_words(program: object, argv: object, *, shell_string: bool = False) -> set[str]:
    """The agent CLIs a spawn may start. An argv ELEMENT resolves to a binary by its
    basename (so ``/usr/bin/env claude`` and ``bwrap ... /opt/agy`` count, while a prompt
    that merely mentions a name does not). A shell's ``-c`` command string, and a whole
    ``os.system`` / ``shell=True`` string, is parsed into words first."""
    if isinstance(argv, (str, bytes, os.PathLike)):
        elements = [argv]
        shell_string = shell_string or " " in _text(argv)
    else:
        elements = list(argv or ())
    if program is not None:
        elements.insert(0, program)
    found = {os.path.basename(_text(e)) for e in elements} & AGENT_CLIS
    texts = [_text(e) for e in elements]
    for index, text in enumerate(texts):
        if os.path.basename(text) in _SHELLS:
            for later, flag in enumerate(texts[index + 1:], start=index + 1):
                if flag.startswith("-") and "c" in flag.lstrip("-") and later + 1 < len(texts):
                    words = _words(texts[later + 1])
                    found |= {os.path.basename(w) for w in words} & AGENT_CLIS
                    found |= agent_words(None, words)  # `sh -c 'sh -c "claude"'`
                    break
    if shell_string:
        for text in texts:
            words = _words(text)
            found |= {os.path.basename(w) for w in words} & AGENT_CLIS
            found |= agent_words(None, words)  # a nested `sh -c "..."` inside the string
    return found


def _runtime_caller() -> str | None:
    """The runtime frame that made this spawn, or ``None`` for a spawn from test code."""
    frame = sys._getframe(2)
    while frame is not None:
        path = frame.f_code.co_filename
        if path == _HOOK_FILE or path.startswith(_STDLIB) or path.startswith("<frozen"):
            frame = frame.f_back
            continue
        resolved = str(Path(path).resolve()) if not path.startswith("<") else path
        for root in RUNTIME_ROOTS:
            if resolved.startswith(root):
                return f"{resolved[len(root):]}:{frame.f_lineno} ({frame.f_code.co_name})"
        return None
    return None


def _decided(env: object) -> bool:
    mapping = os.environ if env is None else env
    try:
        return MARKER in mapping or MARKER.encode() in mapping
    except TypeError:
        return False


def _spawn(event: str, args: tuple) -> tuple[object, object, object] | None:
    """(program, argv, env) for a spawn event; ``None`` for any other event."""
    if event == "subprocess.Popen":
        executable, argv, _cwd, env = args
        return executable, argv, env
    if event in ("os.exec", "os.posix_spawn"):
        path, argv, env = args
        return path, argv, env
    if event == "os.spawn":
        _mode, path, argv, env = args
        return path, argv, env
    if event == "os.system":
        return None, os.fsdecode(args[0]), None
    if event == "pty.spawn":
        return None, args[0], None
    return None


def hook(event: str, args: tuple) -> None:
    if not enabled:
        return
    spawn = _spawn(event, args)
    if spawn is None:
        return
    program, argv, env = spawn
    names = agent_words(program, argv)
    if not names or _decided(env):
        return
    caller = _runtime_caller()
    if caller is None:
        return
    message = (f"{event} of {sorted(names)} from {caller} without a scratch decision "
               f"({MARKER} missing from its env)")
    violations.append(message)
    if log_path is not None:
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            pass


def drain() -> list[str]:
    """Every violation since the last drain, from this process and its forked children."""
    found = list(violations)
    violations.clear()
    if log_path is not None:
        try:
            with open(log_path, "r+", encoding="utf-8") as handle:
                lines = [line.rstrip("\n") for line in handle if line.strip()]
                handle.seek(0)
                handle.truncate()
        except OSError:
            lines = []
        found += [line for line in lines if line not in found]
    return found


_installed = False


def install() -> None:
    global _installed
    if not _installed:
        sys.addaudithook(hook)
        _installed = True
