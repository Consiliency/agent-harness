from __future__ import annotations

import subprocess
from pathlib import Path

from phase_loop_runtime.pipeline_adapter.branch_ops import BranchDecision, ensure_pipeline_branch


def test_ensure_pipeline_branch_creates_from_origin_default(tmp_path, monkeypatch):
    repo = _make_branch_repo(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")

    decision = ensure_pipeline_branch(repo, "v32", "main")

    assert isinstance(decision, BranchDecision)
    assert decision.target_branch == "consiliency/pipeline/v32"
    assert decision.original_branch == "main"
    assert decision.action == "create"
    assert decision.diverged is True  # switched away from main
    assert _git(repo, "branch", "--show-current").stdout.strip() == decision.target_branch
    assert _git(repo, "rev-parse", "HEAD").stdout == _git(repo, "rev-parse", "origin/main").stdout


def test_ensure_pipeline_branch_diverges_from_non_convention_branch(tmp_path, monkeypatch):
    # #44: operator on a non-convention branch holding their roadmap → the runner
    # switches to consiliency/pipeline/<v> and must flag the divergence.
    repo = _make_branch_repo(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")
    _git(repo, "checkout", "-b", "consiliency/ci/v32-restructure")

    decision = ensure_pipeline_branch(repo, "v32", "main")

    assert decision.original_branch == "consiliency/ci/v32-restructure"
    assert decision.target_branch == "consiliency/pipeline/v32"
    assert decision.diverged is True
    assert decision.action in {"create", "checkout"}


def test_ensure_pipeline_branch_stays_when_already_on_convention(tmp_path, monkeypatch):
    # No divergence when already on the convention branch.
    repo = _make_branch_repo(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")
    _git(repo, "checkout", "-b", "consiliency/pipeline/v32")

    decision = ensure_pipeline_branch(repo, "v32", "main")

    assert decision.original_branch == "consiliency/pipeline/v32"
    assert decision.target_branch == "consiliency/pipeline/v32"
    assert decision.action == "stay"
    assert decision.diverged is False


def test_ensure_pipeline_branch_creates_from_explicit_base_ref(tmp_path, monkeypatch):
    repo = _make_branch_repo(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")

    _git(repo, "checkout", "-b", "stacked-base")
    (repo / "stacked.txt").write_text("stacked\n", encoding="utf-8")
    _git(repo, "add", "stacked.txt")
    _git(repo, "commit", "-m", "stacked base")
    _git(repo, "update-ref", "refs/remotes/origin/stacked-base", "HEAD")
    _git(repo, "checkout", "main")
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "main.txt")
    _git(repo, "commit", "-m", "main only")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    decision = ensure_pipeline_branch(repo, "v44", "main", base_ref="origin/stacked-base")

    assert isinstance(decision, BranchDecision)
    assert decision.target_branch == "consiliency/pipeline/v44"
    assert _git(repo, "branch", "--show-current").stdout.strip() == decision.target_branch
    assert _git(repo, "rev-parse", "HEAD").stdout == _git(repo, "rev-parse", "origin/stacked-base").stdout
    assert (repo / "stacked.txt").is_file()
    assert not (repo / "main.txt").exists()


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
