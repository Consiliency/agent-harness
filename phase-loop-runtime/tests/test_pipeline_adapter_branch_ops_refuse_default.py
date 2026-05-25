from __future__ import annotations

import subprocess

from phase_loop_runtime.models import StateSnapshot, utc_now
from phase_loop_runtime.profiles import resolve_profile
from phase_loop_runtime.provenance import snapshot_provenance
from phase_loop_runtime.runner import _perform_phase_closeout
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan


def test_closeout_commit_refuses_enabled_pipeline_default_branch(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    _git(repo, "branch", "-M", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    marker = repo / ".pipeline" / "README.md"
    marker.parent.mkdir()
    marker.write_text("pipeline marker\n", encoding="utf-8")
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "CONTRACT", roadmap, owned_files=("README.md",))
    commit_fixture_paths(repo, "add pipeline marker and plan", marker, plan)
    (repo / "README.md").write_text("phase output\n", encoding="utf-8")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")

    snapshot = StateSnapshot(
        timestamp=utc_now(),
        repo=str(repo),
        roadmap=str(roadmap),
        phases={"CONTRACT": "awaiting_phase_closeout"},
        current_phase="CONTRACT",
        phase_owned_dirty=True,
        phase_owned_dirty_paths=("README.md",),
        closeout_terminal_status="complete",
        **snapshot_provenance(roadmap),
    )

    status, event = _perform_phase_closeout(
        repo,
        roadmap,
        "CONTRACT",
        snapshot,
        resolve_profile("execute"),
        action="execute",
        closeout_mode="commit",
    )

    assert status == "blocked"
    assert event.blocker is not None
    assert event.blocker["blocker_class"] == "branch_sync_conflict"
    assert event.metadata["closeout"]["closeout_action"] == "commit_refused"
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def _git(repo, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
