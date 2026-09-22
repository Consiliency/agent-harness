"""Falsifiers for the batched frozen-blob lookup's parse (agent-harness#945).

The chronology node resolves every (commit, frozen path) pair through one
`git cat-file --batch-check` child instead of one `git rev-parse` child per pair.
The two must answer identically, including on paths a naive whitespace split
would misread, so both are checked against real git output here.

The module keeps ``outside_agent`` out of every node id so the CONFORM
``-k outside_agent`` lifecycle corpus is unchanged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from test_outside_agent_conform_evidence import (
    BATCH_CHECK_FORMAT,
    _batch_check_object_name,
)


AWKWARD_PATHS = (
    "plain.txt",
    "with space.txt",
    "ends in blob",
    "ends in tree",
    "with\ttab",
    "tab\tblob",
)
MISSING_PATHS = (
    "absent.txt",
    "gone blob",
    "gone tree",
    "gone\tblob",
)


@pytest.fixture(scope="module")
def scratch_repository(tmp_path_factory) -> tuple[Path, str]:
    root = tmp_path_factory.mktemp("batch-check-repo")
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    for name in AWKWARD_PATHS:
        (root / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        [
            "git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
            "-c", "commit.gpgsign=false", "commit", "-qm", "fixture",
        ],
        cwd=root,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    return root, head


def _rev_parse(root: Path, spec: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", spec], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _batch_check(root: Path, specs: list[str]) -> list[str | None]:
    result = subprocess.run(
        ["git", "cat-file", f"--batch-check={BATCH_CHECK_FORMAT}"],
        cwd=root,
        input="".join(f"{spec}\n" for spec in specs),
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    assert len(lines) == len(specs), (len(lines), len(specs))
    return [_batch_check_object_name(line) for line in lines]


def test_batch_check_answers_exactly_what_rev_parse_answers(scratch_repository):
    """Present and absent specs, including whitespace-bearing paths."""
    root, head = scratch_repository
    specs = [f"{head}:{name}" for name in (*AWKWARD_PATHS, *MISSING_PATHS)]
    assert _batch_check(root, specs) == [_rev_parse(root, spec) for spec in specs]


def test_present_awkward_paths_resolve_rather_than_reading_as_missing(scratch_repository):
    root, head = scratch_repository
    resolved = _batch_check(root, [f"{head}:{name}" for name in AWKWARD_PATHS])
    assert all(value is not None for value in resolved), dict(zip(AWKWARD_PATHS, resolved))
    assert all(len(value) == 40 for value in resolved), resolved


def test_a_missing_path_ending_in_a_type_word_is_not_read_as_an_object(scratch_repository):
    """The exact shape a whitespace split misreads.

    `git` echoes the input on a `missing` line, so `<oid>:gone blob missing`
    splits into three fields whose second is the literal `blob`. A parser keying
    on `fields[1]` returns `<oid>:gone` as though the object existed. Keying on
    the format's TAB separator cannot: a missing line carries no tab from the
    format string.
    """
    root, head = scratch_repository
    for name in ("gone blob", "gone tree", "gone\tblob"):
        spec = f"{head}:{name}"
        assert _rev_parse(root, spec) is None, spec
        assert _batch_check(root, [spec]) == [None], spec

    # The superseded rule, shown misreading the same real git output.
    raw = subprocess.run(
        ["git", "cat-file", f"--batch-check={BATCH_CHECK_FORMAT}"],
        cwd=root,
        input=f"{head}:gone blob\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[0]
    whitespace_fields = raw.split()
    superseded = (
        whitespace_fields[0]
        if len(whitespace_fields) >= 2 and whitespace_fields[1] in {"blob", "tree", "commit", "tag"}
        else None
    )
    assert superseded is not None, raw
    assert _batch_check_object_name(raw) is None, raw
