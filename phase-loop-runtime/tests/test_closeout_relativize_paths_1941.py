"""Regression tests for Consiliency/agent-harness#1941:
Relativize repo-scoped closeout paths against ``repo_root`` (or an inferred
``.git``/``.phase-loop`` ancestor) so repositories under ``/home/<user>/...`` or
``/Users/<user>/...`` do not trigger ``absolute_private_path`` in
``metadata_redaction_diagnostic`` while external private paths remain rejected.
"""

from __future__ import annotations

import sys
from pathlib import Path

from phase_loop_runtime import runner as runner_mod
from phase_loop_runtime.closeout import (
    build_phase_loop_closeout,
    phase_loop_closeout_diagnostic,
)
from phase_loop_runtime.redaction import metadata_redaction_diagnostic
from phase_loop_runtime.verification_evidence import run_verification


def test_attach_closeout_under_home_like_path_relativizes_plan_path(tmp_path):
    # Explicit synthetic /home/<user>/... path regardless of host TMPDIR.
    repo = tmp_path / "home" / "alice" / "work-repo"
    repo.mkdir(parents=True)
    plan = repo / "plan.md"
    plan.write_text(
        "---\nphase: REL\nphase_loop_mutation: release_dispatch\n---\n# plan\n",
        encoding="utf-8",
    )
    assert metadata_redaction_diagnostic({"plan_path": str(plan)}) is not None
    (repo / "README.md").write_text(
        "Message Board SHA: recovery commit pending\n", encoding="utf-8"
    )
    roadmap = repo / "roadmap.md"
    roadmap.write_text("# roadmap\n", encoding="utf-8")

    out = runner_mod._attach_phase_loop_closeout(
        repo=repo,
        roadmap=roadmap,
        plan=plan,
        phase="REL",
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "automation_status": "complete",
            "automation_human_required": False,
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        changed_paths=("CHANGELOG.md",),
    )
    closeout = out.get("phase_loop_closeout")
    assert closeout is not None
    assert closeout["artifacts"]["plan_path"] == "plan.md"
    assert phase_loop_closeout_diagnostic(closeout) is None


def test_build_closeout_infers_repo_root_and_relativizes_verification_paths(tmp_path):
    repo = tmp_path / "home" / "alice" / "proj"
    plans_dir = repo / "plans"
    plans_dir.mkdir(parents=True)
    plan = plans_dir / "phase-plan-v1-RG.md"
    plan.write_text("# RG plan\nIF-0-RG-1\n", encoding="utf-8")
    run_dir = repo / ".phase-loop" / "runs" / "test-run"
    run_verification(repo, run_dir, [[sys.executable, "-c", "print('ok')"]], None, None, 5)

    closeout = build_phase_loop_closeout(
        phase_alias="RG",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"root": str(run_dir)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
            "artifact": str(plan),
        },
    )

    assert closeout["artifacts"]["plan_path"] == "plans/phase-plan-v1-RG.md"
    assert closeout["artifacts"]["artifact_paths"]["root"] == ".phase-loop/runs/test-run"
    assert closeout["automation"]["artifact"] == "plans/phase-plan-v1-RG.md"
    assert closeout["verification"]["results"][0]["artifact_path"] == (
        ".phase-loop/runs/test-run/verification.json"
    )
    assert closeout["verification"]["results"][0]["log_path"] == (
        ".phase-loop/runs/test-run/verification.log"
    )
    assert phase_loop_closeout_diagnostic(closeout) is None


def test_build_closeout_relativizes_through_symlinked_repo_root(tmp_path):
    real_repo = tmp_path / "home" / "alice" / "real-repo"
    (real_repo / "plans").mkdir(parents=True)
    plan = real_repo / "plans" / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    link_repo = tmp_path / "link-repo"
    link_repo.symlink_to(real_repo)

    closeout = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path=plan,
        terminal_summary={"terminal_status": "complete", "verification_status": "passed"},
        automation={"status": "complete", "verification_status": "passed", "human_required": False},
        repo_root=link_repo,
    )
    assert closeout["artifacts"]["plan_path"] == "plans/plan.md"
    assert phase_loop_closeout_diagnostic(closeout) is None


def test_external_private_path_outside_repo_root_remains_rejected(tmp_path):
    repo = tmp_path / "home" / "alice" / "proj"
    repo.mkdir(parents=True)
    plan = repo / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n", encoding="utf-8")

    closeout = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"leaked": "/home/alice/private/secret.txt"},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        repo_root=repo,
    )

    diagnostic = phase_loop_closeout_diagnostic(closeout)
    assert diagnostic is not None
    assert "absolute_private_path" in diagnostic["message"]
