#!/usr/bin/env python3
"""Assemble ``changelog.d/`` fragments into ``CHANGELOG.md`` at a release cut.

A pull request adds ``changelog.d/<number>.<type>.md`` instead of editing
``CHANGELOG.md`` ``[Unreleased]``, so concurrent pull requests do not all edit the
same lines. ``<number>`` is the agent-harness issue or pull request the entry is
about; ``<type>`` is one of ``TYPES``. A fragment is the entry exactly as it should
read in the CHANGELOG: a ``### `` heading line, then the body.

The release cut runs::

    python scripts/assemble_changelog.py --version 0.7.28

which inserts ``## [0.7.28] - <today>`` directly under ``## [Unreleased]``, then the
fragments (ordered by type, then number), then whatever was already written by hand
under ``[Unreleased]`` -- so hand-written entries land in the same release -- and
deletes the consumed fragments. ``## [Unreleased]`` stays, empty, at the top.

Without ``--version`` the fragments are folded into the top of ``[Unreleased]`` and
no release heading is added. ``--dry-run`` prints the new CHANGELOG and touches
nothing; ``--check`` only validates the fragment names and headings.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

#: Fragment types, in the order they are rendered.
TYPES = ("breaking", "feature", "fix", "change", "docs", "ci")

UNRELEASED = "## [Unreleased]"
FRAGMENT_DIR = "changelog.d"
#: Files in changelog.d/ that are not fragments.
NON_FRAGMENTS = frozenset({"README.md"})

_NAME = re.compile(r"(?P<number>[1-9][0-9]*)\.(?P<type>[a-z]+)(?:\.(?P<part>[1-9][0-9]*))?\.md")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.+][0-9A-Za-z.]+)?")


class FragmentError(ValueError):
    pass


def fragment_paths(root: Path) -> list[Path]:
    directory = root / FRAGMENT_DIR
    if not directory.is_dir():
        return []
    # Everything except README.md, directories included: load_fragments rejects any
    # entry that is not a fragment, so a misplaced entry fails instead of being dropped.
    return sorted(p for p in directory.iterdir() if p.name not in NON_FRAGMENTS)


def _sort_key(path: Path) -> tuple[int, int, int]:
    match = _NAME.fullmatch(path.name)
    assert match is not None
    return (TYPES.index(match["type"]), int(match["number"]), int(match["part"] or 0))


def load_fragments(root: Path) -> list[tuple[Path, str]]:
    """Every fragment, validated and in render order. Raises FragmentError on any bad one."""
    errors: list[str] = []
    loaded: list[tuple[Path, str]] = []
    for path in fragment_paths(root):
        if path.is_symlink() or not path.is_file():
            errors.append(
                f"{FRAGMENT_DIR}/{path.name}: not a regular file; fragments are top-level "
                f"files in {FRAGMENT_DIR}/ (no subdirectories)"
            )
            continue
        match = _NAME.fullmatch(path.name)
        if match is None:
            errors.append(
                f"{FRAGMENT_DIR}/{path.name}: name must be <number>.<type>.md "
                f"(or <number>.<type>.<n>.md for a second entry on the same number)"
            )
            continue
        if match["type"] not in TYPES:
            errors.append(f"{FRAGMENT_DIR}/{path.name}: type {match['type']!r} is not one of {', '.join(TYPES)}")
            continue
        text = path.read_text(encoding="utf-8").strip("\n")
        if not text.startswith("### "):
            errors.append(f"{FRAGMENT_DIR}/{path.name}: must start with a '### ' heading line")
            continue
        if re.search(r"^#{1,2} ", text, flags=re.MULTILINE):
            errors.append(f"{FRAGMENT_DIR}/{path.name}: must not contain '#' or '##' headings")
            continue
        loaded.append((path, text))
    if errors:
        raise FragmentError("\n".join(errors))
    return sorted(loaded, key=lambda item: _sort_key(item[0]))


def assemble(changelog: str, fragments: list[str], version: str | None, date: str) -> str:
    """Return ``changelog`` with ``fragments`` (and a release heading) under [Unreleased]."""
    lines = changelog.splitlines(keepends=True)
    try:
        index = next(i for i, line in enumerate(lines) if line.rstrip("\n") == UNRELEASED)
    except StopIteration:
        raise FragmentError(f"CHANGELOG.md has no '{UNRELEASED}' line") from None
    head = "".join(lines[: index + 1])
    body = "".join(lines[index + 1 :]).lstrip("\n")
    blocks: list[str] = []
    if version is not None:
        blocks.append(f"## [{version}] - {date}")
    blocks.extend(fragments)
    if not blocks:
        return changelog
    inserted = "\n\n".join(blocks)
    return f"{head}\n{inserted}\n\n{body}" if body else f"{head}\n{inserted}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="repository root (default: this script's repository)")
    parser.add_argument("--version", help="add a '## [VERSION] - DATE' release heading")
    parser.add_argument("--date", default=_dt.date.today().isoformat(), help="release date (default: today)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the new CHANGELOG; change nothing")
    mode.add_argument("--check", action="store_true", help="only validate the fragments")
    args = parser.parse_args(argv)

    if args.version is not None and not _VERSION.fullmatch(args.version):
        parser.error(f"--version {args.version!r} is not X.Y.Z")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", args.date):
        parser.error(f"--date {args.date!r} is not YYYY-MM-DD")
    root: Path = args.root
    try:
        loaded = load_fragments(root)
    except FragmentError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.check:
        print(f"{len(loaded)} changelog fragment(s) OK")
        return 0

    changelog_path = root / "CHANGELOG.md"
    try:
        updated = assemble(
            changelog_path.read_text(encoding="utf-8"),
            [text for _, text in loaded],
            args.version,
            args.date,
        )
    except FragmentError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.dry_run:
        sys.stdout.write(updated)
        return 0
    changelog_path.write_text(updated, encoding="utf-8")
    for path, _ in loaded:
        path.unlink()
    print(f"assembled {len(loaded)} fragment(s) into CHANGELOG.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
