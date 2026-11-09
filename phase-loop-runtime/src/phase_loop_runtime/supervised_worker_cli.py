"""Isolated local supervised worker commands; production launch remains gated."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import sys
from typing import Sequence

from .supervised_launch import Refused
from .supervised_dependency import preflight_supervised_route

STATUS_PAGE_SIZE = 50


def _production_codec():
    return None


def read_envelope_file(path: Path, *, cap: int) -> tuple[bytes, int] | Refused:
    from .convergence.adapters.patch_return import _directory_fd
    fd = None
    try:
        parent = _directory_fd(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or info.st_size > cap):
            return Refused("envelope_mode_unsafe")
        data = bytearray()
        while len(data) <= cap:
            chunk = os.read(fd, min(65536, cap + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > cap:
            return Refused("envelope_too_large")
        return bytes(data), info.st_mode
    except (OSError, ValueError):
        return Refused("envelope_file_unsafe")
    finally:
        if fd is not None:
            os.close(fd)


def open_result_file(path: Path, *, excluded: tuple[Path, ...]) -> int | Refused:
    from .convergence.adapters.patch_return import _directory_fd
    try:
        if not path.is_absolute() or ".." in path.parts:
            return Refused("result_path_unsafe")
        resolved = path.resolve()
        if any(resolved == root.resolve() or root.resolve() in resolved.parents for root in excluded):
            return Refused("result_path_unsafe")
        parent = _directory_fd(path.parent)
        try:
            info = os.fstat(parent)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                return Refused("result_path_unsafe")
            return os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
    except (OSError, ValueError):
        return Refused("result_path_unsafe")


def main(argv: Sequence[str] | None = None, *, state_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supervised-worker")
    verbs = parser.add_subparsers(dest="verb", required=True)
    launch = verbs.add_parser("launch")
    launch.add_argument("--envelope", required=True)
    launch.add_argument("--result", required=True)
    for name in ("status", "cancel"):
        command = verbs.add_parser(name)
        target = command.add_mutually_exclusive_group(required=True)
        target.add_argument("--run")
        target.add_argument("--attempt")
        if name == "status":
            command.add_argument("--page", action="store_true")
            command.add_argument("--cursor")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code
    def refuse(reason):
        print(reason)
        return 10
    preflight = preflight_supervised_route("supervised-" + args.verb)
    if isinstance(preflight, Refused):
        return refuse(preflight.reason)
    if not sys.flags.isolated:
        return refuse("isolation_required")
    if args.verb == "launch":
        if _production_codec() is None:
            return refuse("codec_unavailable")
        return refuse("codec_unavailable")
    from . import run_status as journal, run_status_projection as projection
    from .convergence.adapters.patch_return import (default_state_root, evidence_resolver,
        cancel_attempt, PRODUCTION_LAUNCHER_COMMANDS, CANCEL_WAIT_SECONDS)
    state_root = state_root if state_root is not None else default_state_root()
    if args.verb == "cancel":
        print(cancel_attempt(state_root=state_root, run_id=args.run, attempt_id=args.attempt,
                            wait_seconds=CANCEL_WAIT_SECONDS, launcher_commands=PRODUCTION_LAUNCHER_COMMANDS))
        return 0
    if args.cursor and not args.page:
        return 2
    root = journal.open_journal_root(state_root / "journal", create=False)
    if isinstance(root, journal.JournalRefused):
        return refuse(root.code)
    attempt = args.attempt
    if args.run:
        ids = journal.resolve_run(root, args.run)
        if isinstance(ids, journal.JournalRefused) or not ids:
            return refuse("unknown_attempt")
        attempt = ids[-1]
    status = projection.attempt_status(root, attempt)
    page, cursor, diagnostics = None, None, None
    if args.page:
        read = journal.read_attempt(root, attempt)
        if read.identity is None:
            return refuse("unknown_attempt")
        response = projection.read_page(root, json.dumps(dict(assignment_digest=read.identity.assignment_digest,
            page_size=STATUS_PAGE_SIZE, cursor=args.cursor)).encode(), evidence=evidence_resolver(state_root))
        if isinstance(response, journal.JournalRefused):
            return refuse(response.code)
        page, cursor, diagnostics = response.page, response.next_cursor, response.diagnostics
    print(json.dumps(dict(attempt=asdict(status), page=page, next_cursor=cursor, page_diagnostics=diagnostics)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
