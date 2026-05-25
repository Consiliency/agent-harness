from __future__ import annotations

import subprocess
from pathlib import Path

from phase_loop_runtime.pipeline_adapter.branch_ops import ensure_pipeline_branch


def test_ensure_pipeline_branch_creates_from_origin_default(tmp_path, monkeypatch):
    repo = _make_branch_repo(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")

    branch = ensure_pipeline_branch(repo, "v32", "main")

    assert branch == "consiliency/pipeline/v32"
    assert _git(repo, "branch", "--show-current").stdout.strip() == branch
    assert _git(repo, "rev-parse", "HEAD").stdout == _git(repo, "rev-parse", "origin/main").stdout


def _make_branch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
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
