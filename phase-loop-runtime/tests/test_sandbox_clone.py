"""The sandbox is a writable, independent git clone -- not a file copy, not a worktree.

A panelist that can only read a flat copy cannot run `git log`, `git blame` or `git diff`,
which are the cheapest ways to answer "when did this change and why". Measured on this repo,
a depth-50 clone costs 34 MB total (14 MB of it `.git`) against 111 MB for full history,
and reaches 634 commits -- roughly four months. Against a ~150-250 MB used sandbox that is
close to free.

Three properties have to hold together, and each has a way of failing quietly:

* **Independent.** Never `--shared` and never a linked worktree: both leave the sandbox
  resolving objects through the LIVE gitdir, so the reviewed tree stops being a copy.
* **Writable.** `pytest` writes `__pycache__` before it does anything, so a read-only tree
  cannot host a test run. An earlier version hardened the stage to 0o500 and thereby made
  it useless for the one job it exists to do.
* **Faithful.** The sandbox must show what the reviewer is being shown. A bare clone shows
  the last COMMIT, so uncommitted work in the source would silently vanish from the copy.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import review_stage


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    return root


def _commit(root: Path, message: str = "c") -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", message],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _seeded(root: Path) -> Path:
    _repo(root)
    (root / "src.py").write_text("first\n", encoding="utf-8")
    _commit(root, "first")
    (root / "src.py").write_text("second\n", encoding="utf-8")
    _commit(root, "second")
    return root


def test_the_sandbox_has_usable_git_history(tmp_path):
    """`log` and `blame` are the point of cloning rather than copying."""
    repo = _seeded(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert (staged / ".git").exists(), "a panelist needs git, not a flat copy"
    log = subprocess.run(
        ["git", "-C", str(staged), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "second" in log and "first" in log

    blame = subprocess.run(
        ["git", "-C", str(staged), "blame", "--porcelain", "src.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert blame.strip(), "blame must work inside the sandbox"


def test_the_clone_is_independent_of_the_live_gitdir(tmp_path):
    """Never `--shared`: alternates would resolve objects through the live repo."""
    repo = _seeded(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    alternates = staged / ".git" / "objects" / "info" / "alternates"
    assert not alternates.exists(), "an alternates file points at another object store"

    # A linked worktree keeps `.git` as a FILE pointing into the parent gitdir.
    assert (staged / ".git").is_dir(), ".git must be a real directory, not a worktree pointer"

    # Deleting the source must not break the sandbox.
    import shutil
    shutil.rmtree(repo)
    out = subprocess.run(
        ["git", "-C", str(staged), "log", "--oneline"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, "the sandbox must survive the source disappearing"


def test_the_sandbox_is_writable_so_a_test_can_actually_run(tmp_path):
    """The whole point: a panelist forms a hypothesis and RUNS it."""
    repo = _seeded(tmp_path / "repo")
    (repo / "test_thing.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    _commit(repo, "add test")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    # Writing must simply work -- no chmod dance, no PermissionError.
    (staged / "scratch.txt").write_text("panelist note\n", encoding="utf-8")
    (staged / "src.py").write_text("panelist experiment\n", encoding="utf-8")

    run = subprocess.run(
        ["python3", "-m", "pytest", "test_thing.py", "-q", "-p", "no:randomly"],
        cwd=staged, capture_output=True, text=True,
    )
    assert run.returncode == 0, f"a test must run inside the sandbox:\n{run.stdout}\n{run.stderr}"
    assert (staged / "__pycache__").exists() or ".pytest_cache" in os.listdir(staged), (
        "pytest writes caches; a read-only tree cannot host a run"
    )


def test_the_reviewed_tree_is_untouched_by_anything_the_panelist_does(tmp_path):
    """The sandbox protects the tree; that is the whole trust model."""
    repo = _seeded(tmp_path / "repo")
    before = review_stage.review_tree_manifest_sha256(repo)

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    (staged / "src.py").write_text("clobbered\n", encoding="utf-8")
    (staged / "new_file.py").write_text("added\n", encoding="utf-8")
    subprocess.run(["rm", "-rf", str(staged / ".git")], check=True)

    assert review_stage.review_tree_manifest_sha256(repo) == before
    assert (repo / "src.py").read_text(encoding="utf-8") == "second\n"


def test_uncommitted_work_reaches_the_sandbox(tmp_path):
    """A bare clone shows the last COMMIT; the reviewer is shown the working tree.

    If these diverge, a panelist reviews code nobody is proposing -- confidently, with
    citations. The stage must reflect what is actually under review.
    """
    repo = _seeded(tmp_path / "repo")
    (repo / "src.py").write_text("uncommitted edit\n", encoding="utf-8")
    (repo / "brand_new.py").write_text("untracked but not ignored\n", encoding="utf-8")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert (staged / "src.py").read_text(encoding="utf-8") == "uncommitted edit\n"
    assert (staged / "brand_new.py").read_text(encoding="utf-8") == "untracked but not ignored\n"


def test_ignored_paths_still_do_not_reach_the_sandbox(tmp_path):
    repo = _seeded(tmp_path / "repo")
    (repo / ".gitignore").write_text("secrets/\n", encoding="utf-8")
    (repo / "secrets").mkdir()
    (repo / "secrets" / "key.txt").write_text("do not copy\n", encoding="utf-8")
    _commit(repo, "ignore secrets")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert not (staged / "secrets" / "key.txt").exists()


def test_a_deleted_tracked_file_is_absent_from_the_sandbox(tmp_path):
    """The working tree is the truth, including deletions not yet staged."""
    repo = _seeded(tmp_path / "repo")
    (repo / "doomed.py").write_text("bye\n", encoding="utf-8")
    _commit(repo, "add doomed")
    (repo / "doomed.py").unlink()

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert not (staged / "doomed.py").exists(), "a file deleted in the source must not reappear"


def test_the_source_commit_is_recorded_for_staleness_detection(tmp_path):
    """Resuming an idle sandbox has to know whether the branch moved underneath it."""
    repo = _seeded(tmp_path / "repo")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert review_stage.staged_source_commit(staged) == head


def test_a_stale_sandbox_is_detected_when_the_branch_moves(tmp_path):
    repo = _seeded(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert not review_stage.is_stale(staged, repo)

    (repo / "src.py").write_text("moved on\n", encoding="utf-8")
    _commit(repo, "third")
    assert review_stage.is_stale(staged, repo), (
        "a panelist resumed against vanished code reports confident, cited, wrong findings"
    )
