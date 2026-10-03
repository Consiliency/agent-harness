"""Runtime completeness check for agent-CLI scratch decisions (agent-harness#1147).

A static scan of Python cannot be complete: every round of review found another spelling
of a launch (``getattr``, ``functools.partial``, an argv built elsewhere, a runner passed
as a value). This hook does not read source. It watches the interpreter's own audit
events for every process spawn -- ``subprocess.Popen``, ``os.exec*``, ``os.posix_spawn*``,
``os.spawn*``, ``os.system``, ``pty.spawn`` -- and, when the PROGRAM or any argv element
resolves to an agent CLI (after ``env`` / shell ``-c`` parsing), requires the spawn's env
to carry a stamp that PROVES a decision was made for that env:

* the stamp is minted by ``sandbox_policy.child_scratch_env`` and binds the decision, a
  nonce and the env's scratch values under a per-process key
  (``sandbox_policy.scratch_stamp_valid`` re-checks it), so an empty, forged, foreign or
  stale stamp is not a decision;
* an env inherited from this process (no ``env`` passed), or a stamp equal to one this
  process's own environment carries, is not a decision;
* a named EXCEPTION stamp counts only at the launch interface that applies exceptions
  (``launch_provider`` / ``run_provider``).

The agent-CLI names come from the runtime's own registries (``runtime_agent_binaries``),
so a new harness is covered without editing this file.

Only spawns made BY THE RUNTIME are judged: the first frame outside the standard library
must be inside the ``phase_loop_runtime`` package (a spawn with no such frame at all, such
as a thread targeting ``subprocess.run``, is judged too). Test code that starts its own
fake CLIs is not a runtime launch.

Known limits (no audit event, or no hook in the child): native ``execve`` through
``ctypes``/``cffi``, a ``multiprocessing`` "spawn"-method child, and a fresh Python
interpreter that later re-execs.

Violations are recorded, never raised into the spawning code (which may catch and
degrade), and ``conftest.py`` fails the test that produced one at teardown.
"""

from __future__ import annotations

import os
import shlex
import sys
import sysconfig
from pathlib import Path

MARKER = "PHASE_LOOP_SCRATCH_DECIDED"
#: npm package basenames and legacy names of the same CLIs, which no registry lists.
_ALIASES = frozenset({"gemini", "claude-code", "gemini-cli"})


def runtime_agent_binaries() -> frozenset[str]:
    """Every agent-CLI binary the RUNTIME knows, derived from its own registries so a new
    harness is covered without editing this file: the advisor-board harness registry
    (``HarnessSpec.cli``), the panel's leg binaries (``panel_invoker._LEG_CLI``), the
    executor capability registry's probe programs, and the program each launcher
    ``build_<executor>_command`` starts its argv with (read from its source)."""
    import ast
    import inspect

    from phase_loop_runtime import launcher, panel_invoker
    from phase_loop_runtime.advisor_board import registries
    from phase_loop_runtime.capability_registry import capability_registry

    names = {spec.cli for spec in registries._HARNESS_SPECS}
    names |= set(panel_invoker._LEG_CLI.values())
    for record in capability_registry().values():
        names |= {probe.split()[0] for probe in (record.auth_preflight_probes or ()) if probe.split()}
    for name, function in inspect.getmembers(launcher, inspect.isfunction):
        if not (name.startswith("build_") and name.endswith("_command")):
            continue
        for node in ast.walk(ast.parse(inspect.getsource(function))):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.List) and node.value.elts
                    and isinstance(node.value.elts[0], ast.Constant)
                    and any(isinstance(t, ast.Name) and t.id == "command" for t in node.targets)):
                names.add(node.value.elts[0].value)
                break
    return frozenset(names)


AGENT_CLIS = runtime_agent_binaries() | _ALIASES

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


def _runtime_caller() -> tuple[str, str] | None:
    """(location, function) of the runtime frame that made this spawn; ``None`` for a
    spawn from test code. A spawn with NO frame outside the standard library (a thread
    whose target is ``subprocess.run`` itself) cannot be attributed, so it is judged as
    the runtime's: unknown is never assumed safe."""
    frame = sys._getframe(2)
    while frame is not None:
        path = frame.f_code.co_filename
        if path == _HOOK_FILE or path.startswith(_STDLIB) or path.startswith("<frozen"):
            frame = frame.f_back
            continue
        resolved = str(Path(path).resolve()) if not path.startswith("<") else path
        for root in RUNTIME_ROOTS:
            if resolved.startswith(root):
                return (f"{resolved[len(root):]}:{frame.f_lineno} ({frame.f_code.co_name})",
                        frame.f_code.co_name)
        return None
    return ("<unattributed: no frame outside the standard library>", "")


#: The stamp the test process itself carried when the hook was installed: inherited, so
#: never evidence of a decision.
_INHERITED = os.environ.get(MARKER)
#: The only launch sites where a named EXCEPTION decision is applied (the provider launch
#: interface's `child_scratch=`). An exception stamp anywhere else was not set there.
_EXCEPTION_SITES = frozenset({"launch_provider", "run_provider"})


def _decision_problem(env: object, function: str) -> str | None:
    """Why this spawn's env is NOT evidence of a decision made for it; ``None`` if it is."""
    from phase_loop_runtime import sandbox_policy

    if env is None:
        return "it inherits this process's own environment (no env was decided for it)"
    try:
        mapping = {os.fsdecode(k): os.fsdecode(v) for k, v in dict(env).items()}
    except (TypeError, ValueError):
        return "its env cannot be read"
    stamp = mapping.get(MARKER)
    if not stamp:
        return f"{MARKER} is missing or empty"
    if stamp in (os.environ.get(MARKER), _INHERITED):
        return f"{MARKER} was inherited from this process's environment"
    decision = sandbox_policy.scratch_stamp_valid(mapping)
    if decision is None:
        return (f"{MARKER} was not minted for this env (forged, copied from another "
                "process, or its scratch values changed after the decision)")
    if decision != sandbox_policy.CHILD_SCRATCH_RELOCATE and function not in _EXCEPTION_SITES:
        return f"the {decision!r} exception was not applied at its launch site"
    return None


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
    if not names:
        return
    caller = _runtime_caller()
    if caller is None:
        return
    location, function = caller
    problem = _decision_problem(env, function)
    if problem is None:
        return
    message = f"{event} of {sorted(names)} from {location} without a scratch decision: {problem}"
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


_PROBE_EVENT = "phase_loop.scratch_audit_hook.probe"
_probe_seen = False


def _probe(event: str, args: tuple) -> None:
    global _probe_seen
    if event == _PROBE_EVENT:
        _probe_seen = True


def install() -> None:
    """Register the hook and PROVE it is live: an earlier hook can veto registration
    (``sys.addaudithook`` raises then, or the hook never sees events), so a probe event
    must reach it before the suite relies on it."""
    global _installed
    if _installed:
        return
    sys.addaudithook(hook)
    sys.addaudithook(_probe)
    sys.audit(_PROBE_EVENT)
    if not _probe_seen:
        raise RuntimeError("the scratch audit hook did not receive its probe event")
    _installed = True
