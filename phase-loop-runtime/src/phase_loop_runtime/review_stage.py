"""Staged review trees for board seats, and the digest that attests them.

Until now the staged review dir held only ``review-bundle.md`` and
``review-instructions.md``, so a seat could not open the code under review and every
fact it might need had to be inlined into the bundle -- the pressure behind 200-340 KiB
bundles against the 512 KiB transport cap (agent-harness#848).

**Scope, stated plainly.** This module materializes and attests a staged tree. It does
NOT yet deliver that tree to a brokered seat. The ``bwrap --unshare-all --clearenv``
child in ``advisor_board/backing.py`` is a fixed parent-generated posture probe, not a
seat: the seats run in the PARENT via ``_parent_infer``/``_exec_leg``, where brokered
codex is launched with ``--cd <out_dir>`` and brokered gemini drops ``--add-dir``
entirely. Neither argv, nor the broker prompt, nor ``review-instructions.md`` names this
tree. Wiring that delivery changes the attested provider argv and is deliberately not
done here (ah#890 board round 1, fable seat).

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
    """Fail closed on any symlink that could leave the tree, at any mount point.

    Containment is decided TEXTUALLY on the link target rather than by resolving it:
    an absolute target is refused, and a relative target may never traverse above the
    tree root. A textual rule is relocation invariant, so the verdict does not change
    when the stage is bind-mounted at ``/run/phase-loop-review/reviewed-tree``, and it
    does not depend on resolving through intermediate symlinks (each of which is itself
    checked by this same pass, so the whole link graph is covered inductively).

    Note a target that leaves and RE-ENTERS the tree -- e.g.
    ``proc/sys/kernel/leak -> ../../../proc/sys/kernel/hostname`` from three levels down
    -- normalizes back inside and is allowed: ``../../../`` lands exactly on the root,
    not above it. It is in-tree under any mount point. A real escape needs more ``..``
    components than the link's depth.
    """
    for candidate in repo.rglob("*"):
        if not candidate.is_symlink():
            continue
        target = os.readlink(candidate)
        if Path(target).is_absolute():
            raise ValueError(f"review staging refuses absolute symlink: {candidate}")
        rel_dir = candidate.parent.relative_to(root)
        normalized = os.path.normpath(os.path.join(str(rel_dir), target))
        if normalized == ".." or normalized.startswith(".." + os.sep):
            raise ValueError(
                f"review staging refuses symlink escaping source tree: {candidate}"
                f" -> {target} (normalizes to {normalized})"
            )
        # Belt and braces: also refuse anything that RESOLVES outside. The two rules
        # catch different things and the board split on which to keep, so both are
        # applied. Lexical is relocation invariant and does not read the filesystem;
        # resolution catches a target reached through an intermediate symlink. A
        # dangling in-tree link is fine -- the stage is a partial copy by design, so
        # absence is expected and is not an escape.
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"review staging refuses symlink escaping source tree: {candidate}"
                f" -> {target} (resolves to {resolved})"
            ) from exc


def _selected_paths(root: Path) -> list[str]:
    """The path set to hash, on EITHER side of the copy.

    A stage has no ``.git``, so ``review_tree_paths`` returns ``None`` there and the
    walk below is used. The source uses git selection. Both must therefore agree on a
    faithful copy, which means only MATERIALIZED files may be hashed: a tracked file
    deleted from the working tree is listed by ``git ls-files`` but cannot exist in the
    stage, and hashing it on one side only made an honest tree fail validation.
    Dropping it loses nothing -- a deletion still removes the path from the set, which
    still moves the digest.
    """
    rel_paths = review_tree_paths(root)
    if rel_paths is None:
        rel_paths = [
            str(p.relative_to(root))
            for p in root.rglob("*")
            if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(root).parts
        ]
    return sorted(
        rel for rel in rel_paths
        if (root / rel).is_symlink() or (root / rel).is_file()
    )


def review_tree_manifest_sha256(root: Path) -> str:
    """Digest binding the reviewed PATH SET and its BYTES.

    Both halves matter: hashing content alone would let a rename pass unnoticed, and
    hashing paths alone would let a length-preserving edit pass.

    **Every field is fixed width.** A delimited record such as
    ``blob <sha> <len> <path>\n`` is NOT injective, because a path may contain a
    newline (git permits it and ``ls-files -z`` preserves it), so a single file named
    ``"a\nblob <sha-of-empty> 0 b"`` serialized byte-identically to two empty files
    ``a`` and ``b``. Hashing the path instead of embedding it makes every record the
    same length, so the concatenation can be parsed exactly one way.

    Symlinks are recorded by their target text rather than followed, so a stage cannot
    be made to hash like its source by pointing at different bytes.
    """
    root = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    for rel in _selected_paths(root):
        target = root / rel
        if target.is_symlink():
            payload = os.readlink(target).encode("utf-8")
            kind = b"link"
        else:
            payload = target.read_bytes()
            kind = b"blob"
        digest.update(
            kind                                                    # 4 bytes, fixed
            + hashlib.sha256(payload).hexdigest().encode("ascii")   # 64 bytes, fixed
            + b"%020d" % len(payload)                               # 20 bytes, fixed
            + hashlib.sha256(rel.encode("utf-8")).hexdigest().encode("ascii")  # 64, fixed
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
            # `_selected_paths`, not the raw git list: a submodule gitlink is listed by
            # `ls-files` but is a DIRECTORY, and `shutil.copy2` raises IsADirectoryError
            # on it. Filtering here also keeps the staged set identical to the hashed set.
            for rel in _selected_paths(root):
                source = root / rel
                destination = staged / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    os.symlink(os.readlink(source), destination)
                else:
                    shutil.copy2(source, destination)
        _harden_modes(staged)
    except Exception:
        # The tree may already be partially hardened, and a bare rmtree cannot unlink
        # through a 0o500 directory -- it would fail silently and leak the stage.
        remove_review_stage(staged)
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
    if staged.is_symlink():
        # Never traverse or chmod through a symlinked root: that would change
        # permissions on a directory outside the stage.
        staged.unlink(missing_ok=True)
        return
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
