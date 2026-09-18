"""Staged review trees for board seats, and the digest that attests them.

A cross-vendor review seat runs inside the HARDEN review sandbox
(``advisor_board/backing.py``: ``bwrap --unshare-all --clearenv`` with the staged
dir ``--ro-bind``ed). Until now that dir held only ``review-bundle.md`` and
``review-instructions.md``, so a seat could not open the code under review and
every fact it might need had to be inlined into the bundle -- the pressure behind
200-340 KiB bundles against the 512 KiB transport cap (agent-harness#848).

Two rules shape this module:

* **A stage is a copy, never the live tree.** It excludes ``.git`` entirely, so no
  live gitdir and no shared object alternates can be reached through it, and it
  refuses any symlink that leaves the source tree. A seat's write can only ever
  land on the copy.
* **What the seat read is attested.** :func:`review_tree_manifest_sha256` binds the
  path set AND the bytes, so a tree swapped between authorization and launch fails
  closed instead of being reviewed silently.

This module deliberately imports nothing from ``advisor_board`` or ``launcher``:
``launcher`` already imports ``advisor_board``, so a helper either of them could
import must sit below both. ``launcher._stage_review_tree`` implements the same
selection for the product-loop review action; converging the two is tracked
separately, because ``launcher.py`` belongs to an executing phase lane.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = [
    "REVIEW_STAGE_DIR_PREFIX",
    "review_tree_paths",
    "review_tree_manifest_sha256",
    "stage_review_tree",
    "remove_review_stage",
    "REVIEW_STAGE_TREE_DIRNAME",
]

REVIEW_STAGE_DIR_PREFIX = "pl-panel-stage-"

# Fixed name of the staged tree INSIDE the authorized staged dir. Fixed, not
# caller-chosen, so the authorization's digest and the validator refer to the same
# path by construction -- a caller-supplied name could point the check at one
# directory while the seat reads another.
REVIEW_STAGE_TREE_DIRNAME = "reviewed-tree"

# Read-only for the owner: the sandbox binds this tree read-only anyway, but a
# restrictive mode means a seam that runs a seat outside the sandbox still cannot
# quietly rewrite the reviewed bytes.
_STAGED_FILE_MODE = 0o400
_STAGED_DIR_MODE = 0o500


def review_tree_paths(repo: Path) -> list[str] | None:
    """Repo-relative paths a reviewer should see: tracked, plus untracked-but-not-ignored.

    ``None`` when ``repo`` is not a git checkout or git is unavailable, so the
    caller can fall back to a contained full copy.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True, text=True, check=False,
        )
        if tracked.returncode != 0:
            return None
        untracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=False,
        )
        if untracked.returncode != 0:
            return None
    except OSError:
        return None
    seen: set[str] = set()
    for chunk in (tracked.stdout, untracked.stdout):
        for rel in chunk.split("\0"):
            if rel:
                seen.add(rel)
    return sorted(seen)


def _refuse_escaping_symlinks(repo: Path, root: Path) -> None:
    """Fail closed on any symlink pointing outside the tree being staged."""
    for candidate in repo.rglob("*"):
        if not candidate.is_symlink():
            continue
        if Path(os.readlink(candidate)).is_absolute():
            raise ValueError(f"review staging refuses absolute symlink: {candidate}")
        try:
            candidate.resolve(strict=True).relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(
                f"review staging refuses symlink escaping source tree: {candidate}"
            ) from exc


def review_tree_manifest_sha256(root: Path) -> str:
    """Digest binding the reviewed PATH SET and its BYTES.

    Both halves matter. Hashing content alone would let a rename pass unnoticed;
    hashing paths alone would let a length-preserving edit pass. Each record is
    ``<sha256-of-bytes> <byte-length> <relative-path>\\n`` over a sorted path list,
    so the digest is deterministic and order-independent.

    Symlinks are recorded by their target text rather than followed, so a stage
    cannot be made to hash like its source by pointing at different bytes.
    """
    root = Path(root).resolve(strict=True)
    rel_paths = review_tree_paths(root)
    if rel_paths is None:
        rel_paths = sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(root).parts
        )

    digest = hashlib.sha256()
    for rel in rel_paths:
        target = root / rel
        if target.is_symlink():
            payload = os.readlink(target).encode("utf-8")
            kind = b"link"
        elif target.is_file():
            payload = target.read_bytes()
            kind = b"blob"
        else:
            # Recorded as absent so a deletion moves the digest.
            digest.update(b"gone 0 " + rel.encode("utf-8") + b"\n")
            continue
        digest.update(
            kind
            + b" "
            + hashlib.sha256(payload).hexdigest().encode("ascii")
            + b" "
            + str(len(payload)).encode("ascii")
            + b" "
            + rel.encode("utf-8")
            + b"\n"
        )
    return digest.hexdigest()


def stage_review_tree(repo: Path, parent: Path | None = None) -> Path:
    """Materialize a throwaway, read-only copy of ``repo`` for a review seat.

    Never a linked worktree and never ``git clone --shared``: both leave the stage
    pointing into the live gitdir or its object store. This is a plain copy with
    ``.git`` omitted.

    The copy is created under ``parent`` (default: the system temp dir) and is the
    caller's to remove. On any failure the partial copy is removed here rather than
    leaked, and the failure is raised.
    """
    root = Path(repo).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"review root is not a directory: {repo}")

    parent = Path(parent) if parent is not None else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=REVIEW_STAGE_DIR_PREFIX, dir=str(parent)))

    try:
        _refuse_escaping_symlinks(root, root)
        rel_paths = review_tree_paths(root)
        if rel_paths is None:
            shutil.copytree(
                root, staged,
                dirs_exist_ok=True, symlinks=True,
                ignore=shutil.ignore_patterns(".git"),
            )
        else:
            for rel in rel_paths:
                source = root / rel
                if not source.exists() and not source.is_symlink():
                    continue
                destination = staged / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    os.symlink(os.readlink(source), destination)
                else:
                    shutil.copy2(source, destination)
        _harden_modes(staged)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def remove_review_stage(staged: Path) -> None:
    """Remove a stage created by :func:`stage_review_tree`.

    Always use this rather than a bare ``shutil.rmtree``: the stage is deliberately
    read-only (``0o500`` directories), and ``rmtree`` cannot unlink through a
    directory it may not write. Restoring the mode on the way down is what makes
    cleanup reliable; without it a stage leaks on every run.

    Never raises: cleanup runs on failure paths, where losing the original error to
    a cleanup error would be worse than leaking a temp dir.
    """
    staged = Path(staged)
    if not staged.exists():
        return
    for path in sorted(staged.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            continue
        try:
            path.chmod(0o700)
        except OSError:
            pass
    try:
        staged.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(staged, ignore_errors=True)


def _harden_modes(staged: Path) -> None:
    """Make the stage read-only, deepest paths first so parents stay writable."""
    for path in sorted(staged.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            continue
        try:
            path.chmod(_STAGED_FILE_MODE if path.is_file() else _STAGED_DIR_MODE)
        except OSError:
            pass
