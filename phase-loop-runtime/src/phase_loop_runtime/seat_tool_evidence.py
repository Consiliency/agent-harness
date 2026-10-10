"""What a CLI seat's own run record says about its tool calls (agent-harness#1335).

A review seat whose tools could not run is never a usable review. A CLI can still exit 0 and
print a verdict after every command it tried was refused before it started: codex's commands
run inside codex's own bubblewrap sandbox, and where that sandbox cannot start inside the
seat (a host that denies the nested namespace) each attempt ends in the launcher's one-line
diagnostic. The reply then carries a verdict over files the seat never opened.

The record is not complete: for some launcher failures (a read-only workspace root is one)
codex tells the model and writes no exec record at all, in the transcript or under
``--json``. The runtime therefore also probes the capability before the seat runs
(``panel_invoker._codex_command_sandbox_cannot_start``); this module is the check after it.

This module reads the one record of tool attempts the runtime already holds for a codex leg:
the exec blocks of the session transcript codex writes to stderr,

    exec
    <command> in <workdir>
     succeeded in 12ms:          (or `` exited 1 in 0ms:``)
    <output>

It decides from those records only, never from the model's prose or the sentence a launcher
happens to print. Three things keep quoted text from deciding anything:

* the echoed prompt and the final message are removed before parsing (a review bundle or a
  reply may quote a whole transcript);
* a failure counts only as a launcher failure, and at least one of them must have run in the
  seat's OWN working directory, a path under a directory this run created, which no bundle,
  fixture or earlier transcript can name;
* any record that ran, or that this parser cannot read, leaves the leg as it was. A wrong
  answer here can only be "no decision", never a healthy seat marked degraded.

Nothing here launches a process or reads a file's content.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

__all__ = [
    "TOOL_SANDBOX_UNAVAILABLE",
    "ExecRecord",
    "codex_exec_records",
    "codex_tools_never_started",
    "launcher_diagnostic_in",
]

#: The leg detail and seat notice code (``seat_jail.NOTICES`` renders what / why / fix).
TOOL_SANDBOX_UNAVAILABLE = "seat_tool_sandbox_unavailable"

# How a sandbox launcher reports that it could not start, as the first and only line of a
# command's output. bubblewrap prefixes every fatal message with its own name, whatever the
# reason and whatever the version's wording ("No permissions to create new namespace" on
# 0.6, "... create a new namespace" on 0.11, "setting up uid map: Operation not permitted").
_LAUNCHER_DIAGNOSTIC_PREFIXES: tuple[str, ...] = ("bwrap: ",)

_EXEC_HEADER = "exec"
_STATUS_RE = re.compile(r" (?:(?P<ok>succeeded)|exited (?P<code>-?\d{1,6})) in \d+(?:\.\d+)?m?s:")
_COMMAND_LAST_LINE_RE = re.compile(r".* in (?P<workdir>/.*)")


@dataclass(frozen=True)
class ExecRecord:
    """One command codex ran, as its transcript records it."""

    workdir: str
    outcome: str  # "succeeded" | "failed" | "unknown" (a record this parser cannot read)
    exit_code: int | None = None
    #: The line after the status line: the first line of the command's output, or "" when
    #: the next block follows directly. Read only to recognise a launcher diagnostic.
    output_line: str = ""
    #: The output is that one line and nothing else.
    single_line: bool = False

    @property
    def launcher_failure(self) -> bool:
        """The command never started: it failed, and all it printed is the sandbox launcher's
        own one-line diagnostic. A command that ran and failed prints its own output (or
        none), and a run that merely reports a launcher error prints more than one line."""
        return (self.outcome == "failed" and self.single_line
                and self.output_line.startswith(_LAUNCHER_DIAGNOSTIC_PREFIXES))


def launcher_diagnostic_in(output: str) -> bool:
    """Does this output carry a sandbox launcher's own fatal diagnostic (a line that STARTS
    with the launcher's name)? For output the runtime itself asked for -- a probe that runs
    ``true`` -- and never for a model's text."""
    return any(line.startswith(_LAUNCHER_DIAGNOSTIC_PREFIXES)
               for line in (output or "").splitlines())


def codex_exec_records(transcript: str) -> tuple[ExecRecord, ...]:
    """Every exec block in a codex session transcript, in order.

    A block is the header line ``exec``, the command (which may span lines, blank ones
    included) ending in `` in <workdir>``, and a status line. A header with no readable
    command or status after it yields an ``unknown`` record rather than being skipped, so a
    transcript this parser does not understand is never read as "nothing ran"."""
    lines = (transcript or "").splitlines()
    records: list[ExecRecord] = []
    index = 0
    while index < len(lines):
        if lines[index] != _EXEC_HEADER:
            index += 1
            continue
        start = index + 1
        status = start
        match = None
        while status < len(lines):
            if lines[status] == _EXEC_HEADER:
                break  # a new block began: the header above was not followed by a status
            match = _STATUS_RE.fullmatch(lines[status])
            if match:
                break
            status += 1
        if match is None:
            records.append(ExecRecord(workdir="", outcome="unknown"))
            index = status
            continue
        # The command may span lines; its LAST line carries the working directory.
        command = _COMMAND_LAST_LINE_RE.fullmatch(lines[status - 1]) if status > start else None
        if command is None:
            records.append(ExecRecord(workdir="", outcome="unknown"))
            index = status + 1
            continue
        output = lines[status + 1] if status + 1 < len(lines) else ""
        if output == _EXEC_HEADER:
            output = ""  # an empty output is followed directly by the next block
        following = lines[status + 2] if status + 2 < len(lines) else ""
        records.append(ExecRecord(
            workdir=command["workdir"].rstrip(),
            outcome="succeeded" if match["ok"] else "failed",
            exit_code=0 if match["ok"] else int(match["code"]),
            output_line=output,
            single_line=bool(output) and not following.strip(),
        ))
        index = status + 1
    return tuple(records)


def _within(workdir: str, roots: tuple[str, ...]) -> bool:
    return any(workdir == root or workdir.startswith(root.rstrip("/") + "/") for root in roots)


def codex_tools_never_started(transcript: str, *, seat_cwd: str, prompt: str = "",
                              final_message: str = "") -> bool:
    """Did this codex seat try to run commands and have NONE of them start?

    True only when, after the echoed ``prompt`` and the ``final_message`` are removed, the
    transcript holds at least one exec record, every record is a launcher failure, and at
    least one of them ran in ``seat_cwd`` (as given, or resolved). False for a seat that ran
    no command, for one whose commands ran and failed for reasons of their own, and whenever
    a record cannot be read."""
    text = transcript or ""
    for quoted in (prompt, final_message):
        if quoted and quoted.strip():
            text = text.replace(quoted.strip(), "")
    records = codex_exec_records(text)
    if not records or not all(record.launcher_failure for record in records):
        return False
    if not seat_cwd:
        return False
    roots = tuple(dict.fromkeys((os.path.abspath(seat_cwd), os.path.realpath(seat_cwd))))
    return any(_within(record.workdir, roots) for record in records)
