"""Resolve commits by an explicit phase-loop identity trailer."""

from __future__ import annotations

import subprocess
from pathlib import Path


class DeclaredIdentityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeclaredCommitIdentity:
    """Marker type for the declared commit-identity capability."""


def select_declared_commit(repo: Path, revision: str, identity: str) -> str:
    completed = subprocess.run(
        ["git", "log", revision, "--format=%H"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    matches: list[str] = []
    for commit in completed.stdout.splitlines():
        trailers = subprocess.run(
            [
                "git",
                "show",
                "-s",
                "--format=%(trailers:key=Phase-Loop-Identity,valueonly,separator=%x00)",
                commit,
            ],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout.rstrip(b"\n")
        if identity in {
            value.decode("utf-8").strip() for value in trailers.split(b"\x00") if value
        }:
            matches.append(commit)
    if not matches:
        raise DeclaredIdentityError(
            "declared_identity_not_found", f"no commit declares identity {identity!r}"
        )
    if len(matches) != 1:
        raise DeclaredIdentityError(
            "declared_identity_ambiguous", f"multiple commits declare identity {identity!r}"
        )
    return matches[0]
