from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime.pipeline_adapter.branch_ops import PipelineBranchInvariantError, ensure_pipeline_branch


def test_ensure_pipeline_branch_reports_rebase_conflict(tmp_path, monkeypatch):
    repo = _make_branch_repo(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")

    _git(repo, "checkout", "-b", "consiliency/pipeline/v32")
    (repo / "conflict.txt").write_text("pipeline\n", encoding="utf-8")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-m", "pipeline change")
    _git(repo, "checkout", "main")
    (repo / "conflict.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-m", "main change")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "consiliency/pipeline/v32")

    with pytest.raises(PipelineBranchInvariantError) as raised:
        ensure_pipeline_branch(repo, "v32", "main")

    assert raised.value.blocker_class == "merge_conflict"
    assert "conflict.txt" in _git(repo, "status", "--porcelain").stdout


def _make_branch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / ".pipeline").mkdir()
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "-M", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return repo


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
