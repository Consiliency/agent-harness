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


def test_a_sibling_record_that_reached_done_settles_the_plan():
    """The false positive fable found: judging entries in isolation.

    On Consiliency/omniagent-plus, `plans/phase-plan-v1-CLI.md` carries a `committed`
    record with an EMPTY lifecycle alongside a `completed` record whose lifecycle is
    ['executing', 'completed']. The manifest's settled record agrees with the snapshot,
    but entry-at-a-time evaluation reported CLI as contradicting it — a false claim on
    the operator surface, which is the failure mode this detector must not have.
    (ah#830 r1, fable.)
    """
    stub = _entry("CLI", "committed")
    settled = _entry("CLI", "completed")
    assert phase_status_disagreements({"CLI": "complete"}, [stub, settled]) == []
    # order must not matter
    assert phase_status_disagreements({"CLI": "complete"}, [settled, stub]) == []


def test_duplicate_in_flight_records_for_one_plan_collapse_to_one_row():
    """One row per PLAN, not per record — and the row names every status seen.

    Six plan files on that repository carry two entries each, so per-record reporting
    inflated 8 real disagreements into 14 rows and made `render.py` print a phase count
    that was simply wrong.
    """
    out = phase_status_disagreements(
        {"ADAPTERS": "complete"},
        [_entry("ADAPTERS", "committed"), _entry("ADAPTERS", "imported")],
    )
    assert out == [("ADAPTERS", "complete", "committed/imported")]


def test_a_phase_completed_through_a_LATER_plan_is_not_a_contradiction():
    """codex's case: a superseded plan left at `committed` beside a completed one.

    A re-plan leaves the earlier plan file behind. The phase finished — through the new
    plan — so the stores do not disagree, and reporting the stale record would be a
    false claim on the operator surface. An earlier revision of this fix grouped by
    (alias, FILE) and did exactly that. The operator's question is whether this PHASE's
    state is disputed, not whether some individual record is stale. (ah#830 r1, codex.)
    """
    superseded = _entry("P", "committed")
    current = _entry("P", "completed")
    object.__setattr__(current, "file", "plans/phase-plan-v2-P.md")
    assert phase_status_disagreements({"P": "complete"}, [superseded, current]) == []
    assert phase_status_disagreements({"P": "complete"}, [current, superseded]) == []


@pytest.mark.parametrize("snapshot_status", ["planned", "unplanned", "executing", "blocked"])
@pytest.mark.parametrize("manifest_status", ["imported", "committed"])
def test_an_unstarted_plan_is_silent_in_every_non_done_snapshot_state(
    snapshot_status, manifest_status
):
    """ah#312's stated concern, pinned so ah#830 cannot be read as having weakened it.

    That comment says a merely `imported`/`committed` plan "must not warn — that is the
    normal case for a planned-but-unstarted phase and would drown the real signal". Still
    true: the in-flight side is only ever compared against a snapshot in _SNAPSHOT_DONE,
    so the case it protects never reaches the comparison.
    """
    assert phase_status_disagreements(
        {"P": snapshot_status}, [_entry("P", manifest_status)]
    ) == []


def test_a_done_sibling_does_not_mask_the_OTHER_direction():
    """The reconciliation applies only to manifest-in-flight vs snapshot-done.

    The reverse case — manifest `completed`, runner still executing — is the original
    ah#312 defect and must keep firing regardless of siblings.
    """
    out = phase_status_disagreements(
        {"FREEZE": "executing"},
        [_entry("FREEZE", "completed"), _entry("FREEZE", "committed")],
    )
    assert ("FREEZE", "executing", "completed") in out


def _scoped(alias: str, status: str, roadmap_slug: str) -> DotfilesPlanEntry:
    return DotfilesPlanEntry(
        slug=f"{roadmap_slug}-{alias}", file=f"plans/phase-plan-{roadmap_slug}-{alias}.md",
        type="phase", status=status, created_at="t", updated_at="t",
        owner_skill="codex-plan-phase", phase_alias=alias,
        roadmap_ref=DotfilesPlanRef(slug=roadmap_slug, file=f"specs/{roadmap_slug}.md",
                                    type="phase", status="imported"),
    )


def test_another_roadmaps_settled_record_must_not_silence_this_one():
    """A FALSE NEGATIVE, and worse than the r1 false positives: a silent detector is
    undetectable.

    The roadmap filter was applied to the entry under judgement but not to the siblings
    that may settle it, so an entry from a DIFFERENT roadmap — correctly skipped as a
    subject — could still settle an in-scope disagreement. One predicate now serves both.
    (ah#832 r2, grok.)
    """
    in_scope = _scoped("P", "committed", "v2")
    other_roadmap = _scoped("P", "completed", "v1")
    assert phase_status_disagreements(
        {"P": "complete"}, [in_scope], roadmap_slug="v2"
    ) == [("P", "complete", "committed")]
    assert phase_status_disagreements(
        {"P": "complete"}, [in_scope, other_roadmap], roadmap_slug="v2"
    ) == [("P", "complete", "committed")]


def test_the_SAME_roadmaps_settled_record_still_silences_it():
    """The control: scoping must not break the settlement it was added for."""
    assert phase_status_disagreements(
        {"P": "complete"},
        [_scoped("P", "committed", "v2"), _scoped("P", "completed", "v2")],
        roadmap_slug="v2",
    ) == []


def test_another_roadmaps_in_flight_status_must_not_leak_into_the_report():
    """The mis-attribution half: the joined status string is scoped too."""
    out = phase_status_disagreements(
        {"P": "complete"},
        [_scoped("P", "committed", "v2"), _scoped("P", "imported", "v1")],
        roadmap_slug="v2",
    )
    assert out == [("P", "complete", "committed")], out


def test_with_no_roadmap_slug_every_entry_still_participates():
    """Unscoped callers are unaffected — the predicate is a no-op without a slug."""
    out = phase_status_disagreements(
        {"P": "complete"},
        [_scoped("P", "committed", "v2"), _scoped("P", "imported", "v1")],
    )
    assert out == [("P", "complete", "committed/imported")]


def test_the_shape_that_actually_occurs_in_this_repos_manifest():
    """The live case, not a synthetic one: `plans/manifest.json` really carries this.

    At the time this was written, INTEG is `committed` under `phase-plans-v10` AND
    `completed` under `phase-plans-convergence-v1` — different roadmaps, different plan
    files. Before the sibling scan was scoped, the convergence-v1 record silenced INTEG's
    real v10 disagreement. RUNTIME survived only because its sibling happened to be
    `orphaned` rather than `completed`, which is luck, not a guard.

    Reproduced from the real records by a board seat; kept here as a fixture so the shape
    is pinned even after the manifest moves on. (ah#832 r2, fable.)
    """
    integ_v10 = _scoped("INTEG", "committed", "phase-plans-v10")
    integ_convergence = _scoped("INTEG", "completed", "phase-plans-convergence-v1")
    runtime_v10 = _scoped("RUNTIME", "committed", "phase-plans-v10")
    runtime_convergence = _scoped("RUNTIME", "orphaned", "phase-plans-convergence-v1")
    snapshot = {"INTEG": "complete", "RUNTIME": "complete"}
    out = phase_status_disagreements(
        snapshot,
        [integ_v10, integ_convergence, runtime_v10, runtime_convergence],
        roadmap_slug="phase-plans-v10",
    )
    assert sorted(out) == [
        ("INTEG", "complete", "committed"),
        ("RUNTIME", "complete", "committed"),
    ], out


def test_a_completed_entry_is_an_EQUIVALENT_mutant_for_the_continue(tmp_path=None):
    """Recorded so "no survivors" stays honest.

    Deleting the `continue` after the done-vs-in-flight branch survives every test, and
    always will: `completed` is not in `frozenset(TRANSITIONS)`, so the second branch is
    unreachable for an entry that took the first. An equivalent mutant, not a gap — and
    manufacturing a test for it would be the vacuity this file keeps guarding against.
    (ah#832 r2, fable.)
    """
    assert "completed" not in TRANSITIONS
    assert _MANIFEST_DONE.isdisjoint(_MANIFEST_IN_FLIGHT)


def test_the_rendered_header_counts_PHASES_not_rows(monkeypatch):
    """The operator-facing count was unpinned: reverting it left the suite green.

    One phase can contribute more than one contradicting row, so counting rows printed
    "14 phase(s)" for 9 phases — a wrong number on the surface an operator reads to
    decide what to do next. The fix was correct and load-bearing, and nothing asserted
    it. (ah#832 r2, fable.)
    """
    from phase_loop_runtime import render

    clashes = [
        ("ADAPTERS", "complete", "committed"),
        ("ADAPTERS", "complete", "imported"),
        ("UI", "complete", "committed"),
    ]
    monkeypatch.setattr(render, "_manifest_disagreements", lambda snapshot: clashes)
    lines = render._manifest_disagreement_lines(object())
    assert "2 phase(s) differ" in lines[0], lines[0]
    assert "3 phase(s)" not in lines[0]
    assert len(lines) == 1 + len(clashes)


# ---------------------------------------------------------------------------
# THE FOUR SETTLEMENT CASES, one per board round, kept together on purpose.
#
# Each round found a different special case and each patch reintroduced an earlier
# one, so they are pinned as a SET: a change that satisfies three and breaks the
# fourth fails here rather than in the next round.
# ---------------------------------------------------------------------------


def _rec(alias: str, status: str, roadmap_slug: str | None, file: str) -> DotfilesPlanEntry:
    ref = (
        DotfilesPlanRef(slug=roadmap_slug, file=f"specs/{roadmap_slug}.md",
                        type="phase", status="imported")
        if roadmap_slug else None
    )
    return DotfilesPlanEntry(
        slug=f"{status}-{file}", file=file, type="phase", status=status,
        created_at="t", updated_at="t", owner_skill="codex-plan-phase",
        phase_alias=alias, roadmap_ref=ref,
    )


_A = "plans/phase-plan-A.md"
_B = "plans/phase-plan-B.md"


def test_settlement_r1_same_file_committed_beside_completed():
    """r1, fable: `phase-plan-v1-CLI.md` carried a `committed` stub and a `completed`
    record. Judging entries in isolation reported a contradiction the manifest's own
    settled record denied."""
    assert phase_status_disagreements(
        {"P": "complete"}, [_rec("P", "committed", "v2", _A), _rec("P", "completed", "v2", _A)],
        roadmap_slug="v2") == []


def test_settlement_r1_superseded_plan_in_a_different_file_same_roadmap():
    """r1, codex: a phase completed through a LATER plan while the earlier one sits at
    `committed`. Same roadmap, different file — the phase is finished."""
    assert phase_status_disagreements(
        {"P": "complete"}, [_rec("P", "committed", "v2", _A), _rec("P", "completed", "v2", _B)],
        roadmap_slug="v2") == []


def test_settlement_r2_a_DIFFERENT_roadmaps_completed_must_not_settle():
    """r2, all three working seats: live in this repo's manifest — INTEG `committed`
    under phase-plans-v10 and `completed` under phase-plans-convergence-v1. A false
    negative, and a silent detector is undetectable."""
    assert phase_status_disagreements(
        {"P": "complete"}, [_rec("P", "committed", "v2", _A), _rec("P", "completed", "v1", _B)],
        roadmap_slug="v2") == [("P", "complete", "committed")]


def test_settlement_r3_same_file_with_a_legacy_null_roadmap_ref():
    """r3, codex: the r2 scoping fix reintroduced r1's false positive in a narrower case.

    A legacy record carries `roadmap_ref: None`; with the alias appearing twice the
    ambiguous-alias rule excluded it from the siblings, so it could no longer settle its
    own plan file. The ambiguous-alias rule is right to refuse to GUESS a roadmap — but
    it is not guessing when the record names the same plan file, which is a stronger
    association than the frontmatter it is missing.
    """
    assert phase_status_disagreements(
        {"P": "complete"}, [_rec("P", "committed", "v2", _A), _rec("P", "completed", None, _A)],
        roadmap_slug="v2") == []


def test_a_DIFFERENT_phases_completed_record_must_not_settle_this_one():
    """The settlement rule is per PHASE first, and that was unpinned.

    Dropping the alias check from the sibling predicate left the whole suite green — so
    another phase's `completed` record, in the same roadmap, could have settled this
    phase's real disagreement. Found by mutating the fix rather than by review; a
    surviving mutant on a settlement arm is exactly the silent-detector class this file
    has already shipped once.
    """
    out = phase_status_disagreements(
        {"P": "complete", "Q": "complete"},
        [_rec("P", "committed", "v2", _A), _rec("Q", "completed", "v2", _B)],
        roadmap_slug="v2",
    )
    assert ("P", "complete", "committed") in out, out


def test_a_different_phase_sharing_a_plan_file_still_does_not_settle():
    """...and file identity does not override phase identity either."""
    out = phase_status_disagreements(
        {"P": "complete", "Q": "complete"},
        [_rec("P", "committed", "v2", _A), _rec("Q", "completed", "v2", _A)],
        roadmap_slug="v2",
    )
    assert ("P", "complete", "committed") in out, out
