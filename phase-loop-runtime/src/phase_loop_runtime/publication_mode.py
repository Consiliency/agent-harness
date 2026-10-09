"""agent-harness#1392 — the publication mode of the INTERACTIVE execute-phase path.

The runner's publication is governed by ``--closeout-mode``. The interactive path
(an operator invokes ``<harness>-execute-phase`` directly) pushes the feature branch
on its first commit, opens a draft PR and flips it to ready at closeout. This module
gives that path an equivalent control:

* ``none``: no push, no PR. Work stays committed on the local feature branch.
* ``draft-only``: push and open a draft PR; never flip it to ready.
* ``ready``: push, open a draft PR, flip it to ready once verification is green.
  This is the default when nothing is configured.

Two layers may set it, with the same file shape::

    [interactive]
    mode = "none"   # none | draft-only | ready

* the repo: ``.phase-loop-publication.toml`` at the repository root. It is honoured
  only as committed at ``HEAD``, so review can see it. An untracked, ignored, staged
  or modified copy is an error, never read: the runtime-excluded ``.phase-loop/`` is
  not a valid location for the same reason;
* the user: ``$XDG_CONFIG_HOME/agent-harness/publication.toml`` (default
  ``~/.config/agent-harness/publication.toml``).

The MOST RESTRICTIVE layer wins (``none`` < ``draft-only`` < ``ready``). A user cannot
widen what a repo declares, and a user without publish authority can withhold it from
a repo that allows it. A malformed layer is an error, never a silent default.

``phase-loop publication-mode`` prints the resolved mode and the action it requires
(agent-harness#1328 precedent: the tool states its own required action), so the
executing agent never guesses. Any non-zero exit means: do not publish.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:  # Python 3.11+
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Python 3.10 — the requires-python floor
    import tomli as tomllib  # type: ignore[no-redef]

REPO_CONFIG = ".phase-loop-publication.toml"
USER_CONFIG_RELATIVE_PATH = "agent-harness/publication.toml"

# Ordered from most to least restrictive; the resolved mode is the minimum.
PUBLICATION_MODES = ("none", "draft-only", "ready")
DEFAULT_MODE = "ready"

ACTIONS = {
    "none": (
        "do not run git push, gh pr create or gh pr ready. Commit on the local feature "
        "branch only, and report the branch as unpublished (publication_mode=none)."
    ),
    "draft-only": (
        "push the feature branch and open a DRAFT PR (gh pr create --draft). Never run "
        "gh pr ready and never open a ready PR; leave the PR in draft at closeout."
    ),
    "ready": (
        "push the feature branch and open a draft PR on the first commit; flip it to "
        "ready (gh pr ready) at closeout once verification is green."
    ),
}
ERROR_ACTION = (
    "blocked: do not run git push, gh pr create or gh pr ready. Fix the publication "
    "config named above, then run phase-loop publication-mode again."
)


class PublicationConfigError(ValueError):
    """A publication layer is malformed or cannot be trusted. Never a silent default."""


@dataclass(frozen=True)
class Resolution:
    mode: str
    repo_mode: str | None
    user_mode: str | None
    repo_config: Path
    user_config: Path | None

    @property
    def source(self) -> str:
        layers = []
        if self.repo_mode is not None:
            layers.append(f"repo {REPO_CONFIG} at HEAD ({self.repo_mode})")
        if self.user_mode is not None:
            layers.append(f"user {self.user_config} ({self.user_mode})")
        if not layers:
            return f"default ({DEFAULT_MODE}); no repo or user publication config"
        return "most restrictive of: " + ", ".join(layers)


def user_config_path(env: Mapping[str, str] | None = None) -> Path | None:
    """The user file, resolved from the GIVEN environment only (``None``: this process).

    Mirrors ``advisor_board.config._user_config_path``: ``XDG_CONFIG_HOME``, else
    ``HOME``; an environment that names neither has no user layer.
    """
    src = os.environ if env is None else env
    if src.get("XDG_CONFIG_HOME"):
        return Path(src["XDG_CONFIG_HOME"]) / USER_CONFIG_RELATIVE_PATH
    if src.get("HOME"):
        return Path(src["HOME"]) / ".config" / USER_CONFIG_RELATIVE_PATH
    return None


def parse_config(text: str, where: str) -> str | None:
    """The mode a layer declares, or ``None`` when it declares none.

    Unknown tables, unknown keys and values outside ``PUBLICATION_MODES`` are errors.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PublicationConfigError(f"{where}: invalid TOML: {exc}") from None
    for key in data:
        if key != "interactive":
            raise PublicationConfigError(f"{where}: {key} is not a known setting")
    table = data.get("interactive")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise PublicationConfigError(f"{where}: interactive must be a table")
    for key in table:
        if key != "mode":
            raise PublicationConfigError(f"{where}: interactive.{key} is not a known setting")
    if "mode" not in table:
        return None
    mode = table["mode"]
    if mode not in PUBLICATION_MODES:
        raise PublicationConfigError(
            f"{where}: interactive.mode must be one of {', '.join(PUBLICATION_MODES)}; "
            f"got {mode!r}"
        )
    return mode


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def repo_root(repo: Path) -> Path:
    proc = _git(repo, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise PublicationConfigError(f"{repo}: not inside a git work tree")
    return Path(proc.stdout.decode().strip())


def read_repo_mode(root: Path) -> str | None:
    """The repo layer, read from ``HEAD``. Any uncommitted state of the file is an error."""
    status = _git(
        root, "status", "--porcelain", "--ignored", "--untracked-files=all", "--", REPO_CONFIG
    )
    if status.returncode != 0:
        raise PublicationConfigError(
            f"{root / REPO_CONFIG}: git status failed: {status.stderr.decode().strip()}"
        )
    if status.stdout.strip():
        raise PublicationConfigError(
            f"{root / REPO_CONFIG}: is not committed as it stands "
            f"({status.stdout.decode().strip()}). Only the copy committed at HEAD is "
            "honoured; commit it or restore it"
        )
    blob = _git(root, "cat-file", "-p", f"HEAD:{REPO_CONFIG}")
    if blob.returncode != 0:
        return None  # not committed (or no HEAD yet) and nothing on disk: no repo layer
    try:
        text = blob.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise PublicationConfigError(f"{root / REPO_CONFIG}: not UTF-8") from None
    return parse_config(text, f"{REPO_CONFIG} at HEAD")


def read_user_mode(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PublicationConfigError(f"{path}: unreadable: {exc}") from None
    return parse_config(text, str(path))


def resolve(repo: Path | str = ".", *, env: Mapping[str, str] | None = None) -> Resolution:
    root = repo_root(Path(repo))
    user_path = user_config_path(env)
    repo_mode = read_repo_mode(root)
    user_mode = read_user_mode(user_path)
    declared = [m for m in (repo_mode, user_mode) if m is not None]
    mode = min(declared, key=PUBLICATION_MODES.index) if declared else DEFAULT_MODE
    return Resolution(mode, repo_mode, user_mode, root / REPO_CONFIG, user_path)


def main(argv: Sequence[str] | None = None, *, repo: str | None = None) -> int:
    """Print the resolved mode and its required action. Exit 0 resolved, 2 config error."""
    if repo is None:
        import argparse

        parser = argparse.ArgumentParser(prog="phase-loop publication-mode")
        parser.add_argument("--repo", default=".")
        repo = parser.parse_args(argv).repo
    try:
        resolution = resolve(repo)
    except PublicationConfigError as exc:
        print(f"phase-loop publication-mode: {exc}", file=sys.stderr)
        print("publication_mode=error")
        print(f"PUBLICATION_ACTION: {ERROR_ACTION}")
        return 2
    except BaseException:
        # Any other failure still states the blocking action, then keeps its traceback.
        print("publication_mode=error")
        print(f"PUBLICATION_ACTION: {ERROR_ACTION}")
        raise
    print(f"publication_mode={resolution.mode}")
    print(f"source: {resolution.source}")
    print(f"PUBLICATION_ACTION: {ACTIONS[resolution.mode]}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module form
    sys.exit(main())
