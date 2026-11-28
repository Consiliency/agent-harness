"""Regression tests for Consiliency/agent-harness#1941:
Relativize repo-scoped closeout paths against ``repo_root`` (or an inferred
``.git``/``.phase-loop`` ancestor anchored to ``plan_path``) using resolved
containment so repositories under ``/home/<user>/...`` or ``/Users/<user>/...``
do not trigger ``absolute_private_path`` in ``metadata_redaction_diagnostic``,
while symlinks/parent traversals escaping the repo and unrelated checkouts
remain rejected.
"""

from __future__ import annotations

import sys

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


def test_in_repo_symlink_and_parent_escape_are_not_relativized(tmp_path):
    outside = tmp_path / "home" / "alice" / "private"
    outside.mkdir(parents=True)
    secret = outside / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    repo = tmp_path / "home" / "alice" / "proj"
    (repo / "plans").mkdir(parents=True)
    plan = repo / "plans" / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    escape_link = repo / "plans" / "escape-link.txt"
    escape_link.symlink_to(secret)
    parent_escape = f"{repo}/plans/../../private/secret.txt"

    for label, escaping_path in (("symlink", str(escape_link)), ("parent", parent_escape)):
        closeout = build_phase_loop_closeout(
            phase_alias="P1",
            plan_path=plan,
            terminal_summary={
                "terminal_status": "complete",
                "verification_status": "passed",
                "artifact_paths": {label: escaping_path},
            },
            automation={
                "status": "complete",
                "verification_status": "passed",
                "human_required": False,
            },
            repo_root=repo,
        )
        assert closeout["artifacts"]["artifact_paths"][label] == escaping_path
        diagnostic = phase_loop_closeout_diagnostic(closeout)
        assert diagnostic is not None
        assert "absolute_private_path" in diagnostic["message"]


def test_inferred_root_is_anchored_to_plan_and_ignores_unrelated_artifact_checkout(
    tmp_path, monkeypatch
):
    # Relative plan in a directory with no .git/.phase-loop cannot establish a repo root.
    plain_dir = tmp_path / "plain"
    (plain_dir / "plans").mkdir(parents=True)
    (plain_dir / "plans" / "plan.md").write_text("# plan\n", encoding="utf-8")

    unrelated_repo = tmp_path / "home" / "alice" / "other-checkout"
    unrelated_run = unrelated_repo / ".phase-loop" / "runs" / "r1"
    unrelated_run.mkdir(parents=True)

    monkeypatch.chdir(plain_dir)
    closeout = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path="plans/plan.md",
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"root": str(unrelated_run)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
    )

    assert closeout["artifacts"]["artifact_paths"]["root"] == str(unrelated_run)
    diagnostic = phase_loop_closeout_diagnostic(closeout)
    assert diagnostic is not None
    assert "absolute_private_path" in diagnostic["message"]


def test_missing_in_repo_verification_artifact_and_log_keep_blocked_closeout(tmp_path):
    repo = tmp_path / "home" / "alice" / "proj"
    (repo / "plans").mkdir(parents=True)
    plan = repo / "plans" / "phase-plan-v1-RG.md"
    plan.write_text("# RG plan\nIF-0-RG-1\n", encoding="utf-8")

    missing_run = repo / ".phase-loop" / "runs" / "missing-run"
    missing_run.mkdir(parents=True)
    missing_artifact_closeout = build_phase_loop_closeout(
        phase_alias="RG",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"root": str(missing_run)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        repo_root=repo,
    )
    assert missing_artifact_closeout["terminal_status"] == "blocked"
    result_missing_artifact = missing_artifact_closeout["verification"]["results"][0]
    assert result_missing_artifact["code"] == "malformed_artifact"
    assert result_missing_artifact["artifact_path"] == (
        ".phase-loop/runs/missing-run/verification.json"
    )
    assert phase_loop_closeout_diagnostic(missing_artifact_closeout) is None

    missing_log_run = repo / ".phase-loop" / "runs" / "missing-log-run"
    run_verification(repo, missing_log_run, [[sys.executable, "-c", "print('ok')"]], None, None, 5)
    (missing_log_run / "verification.log").unlink()
    missing_log_closeout = build_phase_loop_closeout(
        phase_alias="RG",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"root": str(missing_log_run)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        repo_root=repo,
    )
    assert missing_log_closeout["terminal_status"] == "blocked"
    result_missing_log = missing_log_closeout["verification"]["results"][0]
    assert result_missing_log["code"] == "missing_log"
    assert result_missing_log["log_path"] == ".phase-loop/runs/missing-log-run/verification.log"
    assert phase_loop_closeout_diagnostic(missing_log_closeout) is None


def test_symlink_loop_in_plan_or_artifact_does_not_abort_closeout(tmp_path, monkeypatch):
    repo = tmp_path / "home" / "alice" / "proj"
    (repo / "plans").mkdir(parents=True)
    plan = repo / "plans" / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")

    loop_a = repo / "plans" / "loop-a"
    loop_b = repo / "plans" / "loop-b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)

    # Real OS symlink loop (OSError on Python 3.13+, RuntimeError on Python 3.12).
    closeout = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"loop": str(loop_a)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        repo_root=repo,
    )
    assert closeout["artifacts"]["artifact_paths"]["loop"] == str(loop_a)
    diagnostic = phase_loop_closeout_diagnostic(closeout)
    assert diagnostic is not None
    assert "absolute_private_path" in diagnostic["message"]

    # Explicit Python 3.12 RuntimeError simulation on Path.resolve() for both helpers.
    from pathlib import Path as _Path

    orig_resolve = _Path.resolve

    def _raise_runtime_on_loop(self, strict=False):
        if "py312-loop" in str(self):
            raise RuntimeError(f"Symlink loop from {self}")
        return orig_resolve(self, strict=strict)

    monkeypatch.setattr(_Path, "resolve", _raise_runtime_on_loop)
    py312_loop_plan = repo / "plans" / "py312-loop-plan.md"
    py312_loop_artifact = repo / "plans" / "py312-loop-artifact"
    closeout_py312 = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path=py312_loop_plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"loop": str(py312_loop_artifact)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
    )
    assert closeout_py312["artifacts"]["plan_path"] == str(py312_loop_plan)
    assert closeout_py312["artifacts"]["artifact_paths"]["loop"] == str(py312_loop_artifact)
    diag_py312 = phase_loop_closeout_diagnostic(closeout_py312)
    assert diag_py312 is not None
    assert "absolute_private_path" in diag_py312["message"]

    closeout_py312_explicit = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"loop": str(py312_loop_artifact)},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        repo_root=repo,
    )
    assert closeout_py312_explicit["artifacts"]["plan_path"] == "plans/plan.md"
    assert closeout_py312_explicit["artifacts"]["artifact_paths"]["loop"] == str(
        py312_loop_artifact
    )
    diag_explicit = phase_loop_closeout_diagnostic(closeout_py312_explicit)
    assert diag_explicit is not None
    assert "absolute_private_path" in diag_explicit["message"]


def test_invalid_nul_byte_path_does_not_abort_closeout(tmp_path):
    repo = tmp_path / "home" / "alice" / "proj"
    (repo / "plans").mkdir(parents=True)
    plan = repo / "plans" / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    nul_path = f"{repo}/plans/bad\x00artifact"

    closeout = build_phase_loop_closeout(
        phase_alias="P1",
        plan_path=plan,
        terminal_summary={
            "terminal_status": "complete",
            "verification_status": "passed",
            "artifact_paths": {"bad": nul_path},
        },
        automation={
            "status": "complete",
            "verification_status": "passed",
            "human_required": False,
        },
        repo_root=repo,
    )
    assert closeout["artifacts"]["plan_path"] == "plans/plan.md"
    assert closeout["artifacts"]["artifact_paths"]["bad"] == nul_path
    diagnostic = phase_loop_closeout_diagnostic(closeout)
    assert diagnostic is not None
    assert "absolute_private_path" in diagnostic["message"]
