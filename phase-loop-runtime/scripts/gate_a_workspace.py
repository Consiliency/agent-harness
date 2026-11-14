"""Create Gate A's isolated install tree beneath a trusted operator home."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def validate_directory(path: Path, *, owner: int) -> None:
    if not path.is_absolute() or ".." in path.parts or str(path) != os.path.normpath(str(path)):
        raise ValueError("workspace path must be absolute and canonical")
    # Inspect the supplied spelling; resolving first would hide symlink ancestors.
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        allowed = {owner} if component == path else {0, owner}
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in allowed or info.st_mode & 0o022:
            raise ValueError(f"untrusted workspace directory: {component}")


def create_workspace(home: Path, excluded_roots: tuple[Path, ...]) -> Path:
    owner = os.getuid()
    validate_directory(home, owner=owner)
    excluded = tuple(root.resolve(strict=True) for root in excluded_roots)
    if any(home.is_relative_to(root) for root in excluded):
        raise ValueError("workspace home is inside an excluded checkout")
    workspace = Path(tempfile.mkdtemp(prefix="gate-a-", dir=home))
    try:
        validate_directory(workspace, owner=owner)
        if workspace.stat().st_mode & 0o077 or any(workspace.is_relative_to(root) for root in excluded):
            raise ValueError("workspace is not private or is inside an excluded checkout")
    except BaseException:
        shutil.rmtree(workspace)
        raise
    return workspace


if __name__ == "__main__":
    try:
        print(create_workspace(Path(sys.argv[1]), tuple(Path(value) for value in sys.argv[2:])))
    except (OSError, ValueError) as error:
        raise SystemExit(f"GATE-A FAIL: {error}") from error
