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
    _MANIFEST_DONE,
    _MANIFEST_IN_FLIGHT,
    PLAN_STATUSES,
    TRANSITIONS,
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


def test_manifest_done_vs_snapshot_blocked_is_reported():
    """CR blocker: `blocked` means the runner has outstanding work / needs repair. A
    manifest recording that same phase `completed` is the motivating harm class — this
    stayed SILENT in the first revision."""
    out = phase_status_disagreements({"P": "blocked"}, [_entry("P", "completed")])
    assert out == [("P", "blocked", "completed")]


def test_manifest_failed_vs_snapshot_done_is_deliberately_silent():
    """Documents a DELIBERATE exclusion: done-vs-done outcome disagreement is outside this
    detector's declared scope and has a legitimate staleness reading (a superseded failed
    plan should be orphaned). Pinned so widening it later is a conscious choice."""
    assert phase_status_disagreements({"P": "complete"}, [_entry("P", "failed")]) == []


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


def test_null_roadmap_ref_is_admitted_when_the_alias_is_unambiguous():
    """Legacy entries carry `roadmap_ref: null` (6 exist in the real manifest). If the
    alias appears once, admitting it preserves the signal for an entry whose frontmatter
    is merely missing."""
    e = _entry("FREEZE", "completed")           # no roadmap_ref
    out = phase_status_disagreements({"FREEZE": "executing"}, [e],
                                     roadmap_slug="phase-plans-convergence-v1")
    assert out == [("FREEZE", "executing", "completed")]


def test_null_roadmap_ref_is_skipped_when_the_alias_is_ambiguous():
    """CR: if the same alias appears more than once with no roadmap_ref, we cannot tell
    which roadmap it belongs to — reporting it would name a phase from a DIFFERENT
    roadmap as contradicting the active one, which is actively misleading."""
    dupes = [_entry("FREEZE", "completed"), _entry("FREEZE", "executing")]
    out = phase_status_disagreements({"FREEZE": "executing"}, dupes,
                                     roadmap_slug="phase-plans-convergence-v1")
    assert out == []


def test_manifest_done_vs_snapshot_awaiting_closeout_is_reported():
    """CR round 2: `awaiting_phase_closeout` is in-flight for exactly the reason `blocked`
    is — resume acts on it, and handoff.py couples the two as a pair at three separate
    sites. Admitting one and not its constant companion left a real contradiction silent."""
    out = phase_status_disagreements(
        {"P": "awaiting_phase_closeout"}, [_entry("P", "completed")]
    )
    assert out == [("P", "awaiting_phase_closeout", "completed")]


def test_status_json_also_carries_the_disagreement(monkeypatch, tmp_path):
    """CR round 2 (codex): automation reads `status --json` — repair and handoff flows
    rely on it — so a text-only reconciliation leaves every machine consumer blind.
    Additive key: absent when the stores agree, so no existing consumer changes."""
    import json as _json

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
        def to_json(self):
            return {"roadmap": self.roadmap, "phases": dict(self.phases)}

    out = _json.loads(render.render_status(_Snap(), as_json=True))
    assert "state_disagreements" in out, "status --json is blind to the contradiction"
    assert out["state_disagreements"] == [
        {"phase": "FREEZE", "status": "executing", "manifest": "completed"}
    ]


def test_status_json_omits_the_key_when_the_stores_agree(monkeypatch, tmp_path):
    """Additive-only: a clean run's JSON must be unchanged for existing consumers."""
    import json as _json

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
        phases = {"FREEZE": "complete"}          # agrees with the manifest
        current_phase = None
        ledger_warnings: list = []
        ledger_duplicates_skipped: list = []
        def to_json(self):
            return {"roadmap": self.roadmap, "phases": dict(self.phases)}

    out = _json.loads(render.render_status(_Snap(), as_json=True))
    assert "state_disagreements" not in out


def test_manifest_done_vs_snapshot_executed_is_reported():
    """CR final round (codex): `executed` is resume-actionable — runner.py relaunches the
    execute action for `status in {"planned", "executed"}`, i.e. acceptance/evidence is
    still unresolved. A manifest recording that phase `completed` is the motivating harm
    class. It had been classified DONE, which silenced the pair."""
    out = phase_status_disagreements({"P": "executed"}, [_entry("P", "completed")])
    assert out == [("P", "executed", "completed")]


# ---------------------------------------------------------------------------
# ah#830: the manifest side of the vocabulary admitted ONE of three pre-terminal
# statuses, so `imported` and `committed` plans could never be reported as
# contradicting a `complete` snapshot. Found on Consiliency/omniagent-plus, where the
# shipped literal reported 0 disagreements and the lifecycle-derived set reports 14.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("manifest_status", sorted(TRANSITIONS))
def test_every_pre_terminal_manifest_status_contradicts_a_complete_snapshot(manifest_status):
    """A plan that still has somewhere to go cannot agree with a finished phase.

    Parametrised over the lifecycle table rather than a hand-written list, so a status
    added to TRANSITIONS is covered here the moment it exists.
    """
    out = phase_status_disagreements({"P": "complete"}, [_entry("P", manifest_status)])
    assert out == [("P", "complete", manifest_status)]


def test_in_flight_set_is_derived_from_the_lifecycle_table():
    """The completeness guard: the detector's vocabulary IS the lifecycle's.

    This is the defect, not a restatement of the fix. The set was spelled out as a
    literal `{"executing"}` while TRANSITIONS said three statuses were pre-terminal, and
    nothing tied the two together — so two thirds of the pre-terminal space was
    unreportable and no test could see it. Adding a status to TRANSITIONS must never
    again leave this detector silently behind.
    """
    assert _MANIFEST_IN_FLIGHT == set(TRANSITIONS)
    assert _MANIFEST_IN_FLIGHT == {"imported", "committed", "executing"}


def test_terminal_manifest_statuses_are_never_in_flight():
    """...and the derivation must not sweep the terminal statuses in.

    `failed` and `orphaned` are terminal but deliberately NOT on the done side either;
    that asymmetry is a judgement recorded at `_MANIFEST_DONE`, and this pins that the
    derivation left it intact.
    """
    terminal = set(PLAN_STATUSES) - set(TRANSITIONS)
    assert terminal == {"completed", "failed", "orphaned"}
    assert not (terminal & _MANIFEST_IN_FLIGHT)
    assert _MANIFEST_DONE == {"completed"}


def test_imported_and_committed_were_the_two_that_were_missing():
    """Pins the regression directly: the old literal cannot satisfy this file again."""
    assert {"imported", "committed"} <= _MANIFEST_IN_FLIGHT
    for status in ("imported", "committed"):
        assert phase_status_disagreements({"X": "complete"}, [_entry("X", status)]) == [
            ("X", "complete", status)
        ]


def test_a_failed_plan_against_a_complete_snapshot_stays_silent():
    """Unchanged by ah#830: done-vs-done is outside this detector's declared scope."""
    assert phase_status_disagreements({"P": "complete"}, [_entry("P", "failed")]) == []
    assert phase_status_disagreements({"P": "complete"}, [_entry("P", "orphaned")]) == []


def test_both_contradicting_records_for_one_alias_are_reported():
    """Real shape on omniagent-plus: an alias carries a `committed` AND an `imported` plan.

    Each is a distinct plan record that contradicts the snapshot, so each is reported.
    Collapsing them would hide that two separate records disagree.
    """
    out = phase_status_disagreements(
        {"ADAPTERS": "complete"},
        [_entry("ADAPTERS", "committed"), _entry("ADAPTERS", "imported")],
    )
    assert sorted(out) == [
        ("ADAPTERS", "complete", "committed"),
        ("ADAPTERS", "complete", "imported"),
    ]
