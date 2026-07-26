"""ah#312: the runner snapshot and plans/manifest.json both record phase execution
state, in a shared vocabulary, with nothing reconciling them.

Observed on specs/phase-plans-convergence-v1.md: `phase-loop status` printed
`FREEZE: executing` while the manifest recorded that phase `completed`. A phase stuck at
`executing` that is actually finished is exactly the state that makes resume/dispatch do
the wrong thing, and status alone cannot distinguish it from a genuinely live phase.

Status must SURFACE the disagreement rather than silently rendering one store.
"""
from __future__ import annotations

import pytest

from phase_loop_runtime.plan_manifest import (
    DotfilesPlanEntry,
    DotfilesPlanRef,
    phase_status_disagreements,
)


def _entry(alias: str, status: str, roadmap_slug: str | None = None) -> DotfilesPlanEntry:
    ref = (
        DotfilesPlanRef(slug=roadmap_slug, file=f"specs/{roadmap_slug}.md", type="phase",
                        status="imported")
        if roadmap_slug else None
    )
    return DotfilesPlanEntry(
        slug=f"v1-{alias}", file=f"plans/phase-plan-v1-{alias}.md", type="phase",
        status=status, created_at="t", updated_at="t", owner_skill="codex-plan-phase",
        phase_alias=alias, roadmap_ref=ref,
    )


def test_manifest_done_vs_snapshot_executing_is_reported():
    """The exact observed case: manifest says completed, runner says executing."""
    out = phase_status_disagreements({"FREEZE": "executing"}, [_entry("FREEZE", "completed")])
    assert out == [("FREEZE", "executing", "completed")]


def test_manifest_executing_vs_snapshot_complete_is_reported():
    """The mirror case — neither store is privileged."""
    out = phase_status_disagreements({"X": "complete"}, [_entry("X", "executing")])
    assert out == [("X", "complete", "executing")]


@pytest.mark.parametrize("snap,man", [("complete", "completed"), ("executing", "executing")])
def test_agreement_is_silent(snap, man):
    assert phase_status_disagreements({"P": snap}, [_entry("P", man)]) == []


@pytest.mark.parametrize("man", ["imported", "committed"])
def test_a_plan_that_never_executed_is_not_a_contradiction(man):
    """`imported`/`committed` mean the plan DOCUMENT exists — they say nothing about
    execution. Warning here would fire on every planned-but-unstarted phase and drown the
    real signal."""
    assert phase_status_disagreements({"P": "planned"}, [_entry("P", man)]) == []


def test_unplanned_phase_is_not_a_contradiction():
    assert phase_status_disagreements({"P": "unplanned"}, [_entry("P", "completed")]) == []


def test_entries_from_a_different_roadmap_are_ignored():
    """A manifest carries entries for MANY roadmaps; only the active one is comparable."""
    out = phase_status_disagreements(
        {"FREEZE": "executing"},
        [_entry("FREEZE", "completed", roadmap_slug="some-other-roadmap")],
        roadmap_slug="phase-plans-convergence-v1",
    )
    assert out == []


def test_status_output_surfaces_the_disagreement(monkeypatch, tmp_path):
    """Drives the REAL `render_status`, not the helper — an earlier revision called the
    helper directly and therefore survived deleting its call site."""
    from phase_loop_runtime import render
    import phase_loop_runtime.plan_manifest as pm

    monkeypatch.setattr(render, "attach_git_topology", lambda repo, snap: snap)
    monkeypatch.setattr(
        pm, "read_manifest",
        lambda repo: type("M", (), {"plans": [_entry("FREEZE", "completed")]})(),
    )

    class _Snap:
        repo = str(tmp_path)
        roadmap = "specs/phase-plans-convergence-v1.md"
        phases = {"FREEZE": "executing"}
        current_phase = None
        ledger_warnings: list = []
        ledger_duplicates_skipped: list = []
        dirty_paths: list = []
        phase_owned_dirty = False
        phase_owned_dirty_paths: list = []
        previous_phase_owned_paths: list = []
        unowned_dirty_paths: list = []
        pre_existing_dirty_paths: list = []
        metrics_summary = None
        human_required = False
        closeout_summary = None
        git_topology = None
        blocker_class = None
        blocker_summary = None
        terminal_status = None
        terminal_verification = None
        terminal_summary = None
        closeout_evidence = None
        execution_policy = None
        current_terminal = None

    out = render.render_status(_Snap())
    assert "STATE DISAGREEMENT" in out, "render_status did not surface the contradiction"
    assert "FREEZE" in out and "executing" in out and "completed" in out
