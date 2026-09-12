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

from phase_loop_runtime.models import PHASE_STATUSES
from phase_loop_runtime.plan_manifest import (
    _CENSUS_IDENTITY_FIELDS,
    ParseablePlanRows,
    _roadmap_claim,
    _MANIFEST_DONE,
    _MANIFEST_IN_FLIGHT,
    _SNAPSHOT_DONE,
    _SNAPSHOT_EXCLUDED,
    _SNAPSHOT_IN_FLIGHT,
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
        # The seam render actually calls. It was `read_manifest` until r8 moved the
        # read to a per-row parse; a monkeypatch left on the old name would have gone
        # vacuous silently — the test would patch a function nobody calls, the real
        # manifest would be read instead, and the assertion would pass or fail for
        # reasons unrelated to what it claims. (ah#832 r8.)
        pm, "parseable_plan_entries",
        lambda repo: ParseablePlanRows(entries=(_entry("FREEZE", "completed"),)),
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
        # The seam render actually calls. It was `read_manifest` until r8 moved the
        # read to a per-row parse; a monkeypatch left on the old name would have gone
        # vacuous silently — the test would patch a function nobody calls, the real
        # manifest would be read instead, and the assertion would pass or fail for
        # reasons unrelated to what it claims. (ah#832 r8.)
        pm, "parseable_plan_entries",
        lambda repo: ParseablePlanRows(entries=(_entry("FREEZE", "completed"),)),
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
        # The seam render actually calls. It was `read_manifest` until r8 moved the
        # read to a per-row parse; a monkeypatch left on the old name would have gone
        # vacuous silently — the test would patch a function nobody calls, the real
        # manifest would be read instead, and the assertion would pass or fail for
        # reasons unrelated to what it claims. (ah#832 r8.)
        pm, "parseable_plan_entries",
        lambda repo: ParseablePlanRows(entries=(_entry("FREEZE", "completed"),)),
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


@pytest.mark.parametrize(
    "snapshot_status", sorted(set(PHASE_STATUSES) - set(_SNAPSHOT_DONE))
)
@pytest.mark.parametrize("manifest_status", ["imported", "committed"])
def test_an_unstarted_plan_is_silent_in_every_non_done_snapshot_state(
    snapshot_status, manifest_status
):
    """ah#312's stated concern, pinned so ah#830 cannot be read as having weakened it.

    That comment says a merely `imported`/`committed` plan "must not warn — that is the
    normal case for a planned-but-unstarted phase and would drown the real signal". Still
    true: the in-flight side is only ever compared against a snapshot in _SNAPSHOT_DONE,
    so the case it protects never reaches the comparison.

    The snapshot axis is DERIVED from models.PHASE_STATUSES, not hand-listed. It was
    hand-listed as four statuses, which is how the source comment came to claim it had
    verified "every combination" while `unknown`, `executed` and
    `awaiting_phase_closeout` were never exercised at all — the same hand-listing defect
    ah#830 exists to fix, one level up in the test. Deriving it means a status added to
    the table is covered here whether or not anyone remembers this file. (ah#832 r6.)
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


def test_the_ONLY_equivalent_continue_is_the_no_attributable_guard():
    """Recorded so "no survivors" stays honest — and re-measured, not re-argued.

    The r2 version of this test claimed the `continue` after the done-vs-in-flight branch
    was an equivalent mutant. That `continue` no longer exists: r5 turned the per-record
    loop into a per-phase if/elif. Mutating each of the three surviving `continue`s to
    `pass` (anchors verified, one match each):

      absent-from-snapshot guard  -> CAUGHT (KeyError; 1 test)
      no-attributable guard       -> SURVIVES, and is genuinely equivalent
      settlement continue         -> CAUGHT (8 tests)

    The middle one cannot be caught by any input: with no attributable record the status
    set is EMPTY, and the empty set intersects neither operand, so both branches append
    nothing whether the guard returns early or falls through. That is an equivalence
    argument about the operands, which is what this asserts — manufacturing a test for it
    would be the vacuity this file keeps guarding against. (ah#832 r6, fable.)
    """
    # The equivalence, stated over the operands rather than over the source text.
    assert set() & _MANIFEST_DONE == set()
    assert set() & _MANIFEST_IN_FLIGHT == set()
    # And a phase whose only records are unattributable is silent in BOTH directions,
    # which is the behaviour the guard and the fall-through share.
    foreign = [_rec("P", "completed", "other-roadmap", _A)]
    assert phase_status_disagreements({"P": "executing"}, foreign, roadmap_slug="v2") == []
    assert phase_status_disagreements({"P": "complete"}, foreign, roadmap_slug="v2") == []
    assert _MANIFEST_DONE.isdisjoint(_MANIFEST_IN_FLIGHT)


def test_the_rendered_header_counts_PHASES_not_rows(monkeypatch):
    """The operator-facing count was unpinned: reverting it left the suite green.

    When this landed, one phase could contribute more than one contradicting row, so
    counting rows printed "14 phase(s)" for 9 phases — a wrong number on the surface an
    operator reads to decide what to do next. The fix was correct and load-bearing, and
    nothing asserted it. (ah#832 r2, fable.)

    r5's per-phase loop now emits at most one row per phase, so no input the DETECTOR
    produces can tell the two counts apart. The rows are therefore injected directly:
    `_manifest_disagreement_lines` must be correct for whatever it is handed, and the
    one-row-per-phase property lives in another module. Without the injection this test
    would have gone quietly vacuous at r5. (ah#832 r6.)
    """
    from phase_loop_runtime import render

    clashes = [
        ("ADAPTERS", "complete", "committed"),
        ("ADAPTERS", "complete", "imported"),
        ("UI", "complete", "committed"),
    ]
    monkeypatch.setattr(render, "_manifest_disagreements", lambda snapshot: (clashes, True))
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


# ---------------------------------------------------------------------------
# Three guards that were CORRECT but unpinned — found by mutating the fix, not by
# reading it. Each survived the whole suite while breaking on real data or real
# policy. (ah#832 r3, fable.)
# ---------------------------------------------------------------------------


def test_an_entry_for_a_phase_absent_from_the_snapshot_is_skipped_not_looked_up():
    """The sharpest silencing path in this function, and nothing pinned it.

    Deleting `alias not in snapshot_phases` passes every test here, then raises KeyError
    on the real manifest — this repository carries v4 aliases (PNL*, ROADMAP) that the
    v10 snapshot does not contain. `render.py`'s reconciliation is wrapped in a bare
    `except Exception: return []` so that `status` can never break, which is reasonable
    on its own and means that KeyError does not surface as an error: the detector simply
    goes **entirely silent**.

    A guard whose failure mode is silence must be pinned by something other than the
    happy path.
    """
    entries = [
        _rec("PRESENT", "committed", "v2", _A),
        _rec("ABSENT_FROM_SNAPSHOT", "committed", "v2", _B),
    ]
    out = phase_status_disagreements({"PRESENT": "complete"}, entries, roadmap_slug="v2")
    assert out == [("PRESENT", "complete", "committed")], out


def test_orphaned_and_failed_records_do_NOT_settle_a_phase():
    """`_MANIFEST_DONE` is `{"completed"}` deliberately; widening it passed every test.

    An orphaned or failed plan did not finish the work, so it cannot settle the phase
    against a snapshot claiming completion. The live fixture that carries an `orphaned`
    record never exercised this, because roadmap scoping filtered that record out before
    the settle check ever saw it.
    """
    for terminal_but_not_done in ("orphaned", "failed"):
        out = phase_status_disagreements(
            {"P": "complete"},
            [_rec("P", "committed", "v2", _A), _rec("P", terminal_but_not_done, "v2", _B)],
            roadmap_slug="v2",
        )
        assert out == [("P", "complete", "committed")], (terminal_but_not_done, out)


def test_alias_ambiguity_counts_EVERY_entry_not_only_the_null_ref_ones():
    """Restricting the ambiguity count to null-ref entries passed, and is not equivalent.

    The ambiguity rule exists to refuse attributing a null-ref entry when the alias is
    claimed by more than one roadmap. Counting only null-ref entries misses exactly the
    case it is for: one null-ref entry alongside one explicitly-scoped entry for a
    DIFFERENT roadmap. The existing ambiguity test builds its case from two nulls, so it
    could not see the difference.
    """
    # The null-ref entry must be IN-FLIGHT for the two behaviours to differ: a
    # `completed` one is done-vs-done either way and reports nothing, which is why the
    # first version of this test passed under the mutant it was written to kill.
    null_ref = _rec("P", "committed", None, _B)
    foreign = _rec("P", "completed", "v1", _A)
    out = phase_status_disagreements({"P": "complete"}, [null_ref, foreign], roadmap_slug="v2")
    # HEAD: alias P is claimed by two entries, so the null-ref one cannot be attributed
    # to v2 and is not judged. Counting only null-ref entries would call P unambiguous,
    # admit it, and report a phase that may belong to another roadmap entirely.
    assert out == [], out


def test_settlement_r4_a_legacy_record_settles_the_phase_not_just_its_own_file():
    """r4, codex: r1 and r3's shapes TOGETHER, which no single-case test caught.

        plans/A.md  roadmap v2    committed
        plans/A.md  roadmap null  completed
        plans/B.md  roadmap v2    committed

    A settled against its same-file sibling; B did not, because that sibling is a legacy
    null-ref record the ambiguity rule keeps out of scope. So the phase reported as
    disputed while one of its own plans had completed it.

    The cause was structural, not a missing condition: settlement was decided per
    CANDIDATE using that candidate's file. It is a property of the PHASE and is now
    computed once, with file association resolved transitively first.
    """
    entries = [
        _rec("P", "committed", "v2", _A),
        _rec("P", "completed", None, _A),
        _rec("P", "committed", "v2", _B),
    ]
    assert phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2") == []
    # order must not matter — the closure is computed before any judgement
    assert phase_status_disagreements(
        {"P": "complete"}, list(reversed(entries)), roadmap_slug="v2") == []


def test_r4_does_not_let_a_FOREIGN_file_association_settle_the_phase():
    """The control for r4: file association must start from an IN-SCOPE record.

    If a legacy null-ref `completed` record shares a file with another roadmap's entry
    only, it is not attributable here and must not settle — otherwise the r4 remedy
    reintroduces r2's false negative through the file arm.
    """
    entries = [
        _rec("P", "committed", "v2", _A),          # in scope, in flight
        _rec("P", "completed", None, "plans/C.md"),  # legacy, unrelated file
        _rec("P", "imported", "v1", "plans/C.md"),   # foreign roadmap, same file as above
    ]
    out = phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2")
    assert out == [("P", "complete", "committed")], out


def test_a_record_with_no_plan_file_is_not_attributable_by_file():
    """A record naming no plan file must not be attributable by file.

    Otherwise a legacy record carrying no plan file at all matches any other record whose
    file is also missing, and settles a phase on the strength of two absent values being
    equal. The guard is the candidate clause `plan_file(e) is not None`; this test kills
    its removal. It does NOT reach the seed set's old `- {None}` strip, which
    short-circuited behind that clause — an equivalent mutant either way, so the strip was
    removed rather than left as a line no test could exercise. (ah#832 r6.)
    """
    # The null file must be on the IN-SCOPE side, because that is the side the seed set
    # is built from. My first version of this test put it on the out-of-scope record, so
    # the seed was {_A} either way and the guard was never exercised — the mutant that
    # removes it survived. A test that does not reach the line it names is not coverage.
    # EVERY SPELLING THE PARSER CAN EMIT, not just the object. `_entry_from_json` does
    # `str(data.get("file", ""))`, so a missing key becomes `""` and an explicit
    # `"file": null` becomes the literal `"None"` — the `None` object never reaches here.
    # A guard written against the object alone was dead in production, and the two
    # placeholders compared equal to each other, so two records naming no plan at all
    # matched as though they named the same one. (r5, fable.)
    for absent in (None, "", "None", "  "):
        entries = [
            _rec("P", "committed", "v2", absent),      # in scope, names no plan
            _rec("P", "completed", None, absent),      # LEGACY, also names no plan
        ]
        out = phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2")
        assert out == [("P", "complete", "committed")], (absent, out)
    # control: a REAL shared file must still settle
    assert phase_status_disagreements(
        {"P": "complete"},
        [_rec("P", "committed", "v2", _A), _rec("P", "completed", None, _A)],
        roadmap_slug="v2") == []


def test_a_file_named_only_by_an_OUT_OF_SCOPE_record_does_not_seed_the_closure():
    """The closure must start from in-scope records, or r2's false negative returns.

    A `completed` record in another roadmap, naming a file no in-scope record names, is
    not attributable to this phase in this roadmap and must not settle it.

    THE SECOND CASE IS THE ONE THAT ACTUALLY REACHES THE SEED SET, and until ah#832 r6
    this test had only the first. Widening the seed to every record does NOT red case 1:
    the foreign record claims a roadmap, so the file arm's `not claims_a_roadmap` clause
    rejects it whatever the seed contains, and the test passed under the very mutant its
    docstring claimed to control. Case 2 puts a LEGACY record (null ref, so it passes
    that clause) on the foreign record's file, with the alias ambiguous so it is not in
    scope directly. Then the seed is the only thing standing between that file and
    attribution — measured: green on correct code, red under the widened seed.
    """
    entries = [_rec("P", "committed", "v2", _A), _rec("P", "completed", "v1", "plans/Z.md")]
    out = phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2")
    assert out == [("P", "complete", "committed")], out

    # Case 2: a legacy record sitting on the OUT-OF-SCOPE record's file.
    entries = [
        _rec("P", "committed", "v2", _A),                 # in scope, in flight
        _rec("P", "completed", "v1", "plans/Z.md"),        # ANOTHER roadmap, file Z
        _rec("P", "completed", None, "plans/Z.md"),        # legacy, also file Z
    ]
    out = phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2")
    assert out == [("P", "complete", "committed")], out


def test_a_same_file_record_TAGGED_to_another_roadmap_does_not_settle():
    """r4, fable: the file arm was letting r2's defect back in.

    A record naming a DIFFERENT roadmap has already said where it belongs, and the right
    response is to believe it — that is r2's whole finding. Admitting it on a shared
    filename let a v1-tagged `completed` settle a v2 phase.

    The arm exists for the record that makes NO claim: a legacy entry with
    `roadmap_ref: null` cannot be attributed by frontmatter it does not have. Refusing to
    guess a roadmap is right; declining to read an explicit one is not.
    """
    out = phase_status_disagreements(
        {"P": "complete"},
        [_rec("P", "committed", "v2", _A), _rec("P", "completed", "v1", _A)],
        roadmap_slug="v2",
    )
    assert out == [("P", "complete", "committed")], out


def test_branch_one_also_dedups_its_rows():
    """r4, fable: only the in-flight branch had the dedup, so the done-vs-in-flight branch
    could print one phase twice.

    Two `completed` records for one phase against an `executing` snapshot emitted two
    identical operator lines. Unreachable on today's data and absent from `origin/main`
    too, but the asymmetry is arbitrary: the same phase should occupy one row in both
    directions.
    """
    out = phase_status_disagreements(
        {"FREEZE": "executing"},
        [_rec("FREEZE", "completed", "v2", _A), _rec("FREEZE", "completed", "v2", _B)],
        roadmap_slug="v2",
    )
    assert out == [("FREEZE", "executing", "completed")], out


def test_a_legacy_same_file_record_can_BE_the_subject_not_only_settle():
    """r5, codex: the file arm was one-directional.

    A legacy same-file record could SETTLE a phase but could never be the SUBJECT of the
    original ah#312 comparison, because the ambiguity rule skipped it when picking
    candidates. So `completed` in the manifest against `executing` in the snapshot — the
    exact defect ah#312 exists for — went silent whenever the completed record was the
    legacy one.

    Attribution is a property of the phase. Deciding it once and asking both questions of
    that set is the only shape in which the two directions cannot disagree about which
    records speak for the phase.
    """
    entries = [_rec("P", "committed", "v2", _A), _rec("P", "completed", None, _A)]
    out = phase_status_disagreements({"P": "executing"}, entries, roadmap_slug="v2")
    assert out == [("P", "executing", "completed")], out


def test_a_failed_scoped_record_does_not_hide_a_legacy_in_flight_one():
    """r5, codex's second case: `failed` is terminal but deliberately not `done`.

    With the scoped record `failed` and a legacy same-file record `committed` against a
    `complete` snapshot, the phase is not settled — `failed` never settles — and the
    legacy in-flight record contradicts the snapshot. Previously silent.
    """
    entries = [_rec("P", "failed", "v2", _A), _rec("P", "committed", None, _A)]
    out = phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2")
    assert out == [("P", "complete", "committed")], out


# ---------------------------------------------------------------------------
# ah#832 r6 (fable, BLOCKING): the SNAPSHOT operand had the very defect ah#830
# exists to fix. `_SNAPSHOT_IN_FLIGHT` was hand-listed while
# `models.PHASE_STATUSES` is its authoritative table, and `unknown` — the name
# reconcile gives a still-`executing` phase on a dirty tree — was in neither set,
# so the flagship ah#312 case went silent the moment the tree was dirty.


def test_the_DIRTY_TREE_disguise_of_executing_is_still_reported():
    """The flagship ah#312 case, wearing the name reconcile gives it on a dirty tree.

    `reconcile.py:108` is `phases[phase] = "unknown" if _dirty(repo) else "executing"`.
    Same phase, same hazard, different label — and the label is the one the operator
    sees while the tree is dirty, which is exactly when resume/dispatch is about to act.
    Silent here means silent in the case the detector was written for.
    """
    assert phase_status_disagreements({"P": "unknown"}, [_entry("P", "completed")]) == [
        ("P", "unknown", "completed")
    ]


def test_every_non_done_snapshot_status_reports_a_completed_manifest_except_unplanned():
    """The whole snapshot operand, driven from the authoritative table.

    Enumerating the statuses by hand is the defect this pins: the hand-list omitted
    `unknown`. Derived from `models.PHASE_STATUSES`, so a status added to the table
    lands in this assertion whether or not anyone remembers this file.
    """
    from phase_loop_runtime.models import PHASE_STATUSES

    # SKIP ONLY THE LITERAL, and pin the exclusion set itself.
    #
    # This used to read `if status in _SNAPSHOT_EXCLUDED: continue`, taking its
    # expectation from the operand under judgement — so a mutation that ADDED a status to
    # `_SNAPSHOT_EXCLUDED` made the test excuse the very status it had just silenced, and
    # the test stayed green with its own name ("except unplanned") now false. Adding
    # `planned` survived all 68 tests and the whole mutation matrix. That is the r6
    # blocking defect one level up: the hand-listing was fixed on the snapshot axis and
    # left on the exclusion axis. (ah#832 r7, fable.)
    assert _SNAPSHOT_EXCLUDED == {"unplanned"}, _SNAPSHOT_EXCLUDED
    # The r6 defect, stated as the property rather than as a set-shape mirror: `unknown`
    # was in NEITHER operand, so it was unreportable. Naming it here means a re-hand-listing
    # that drops it fails on the name of the status, not on a derivation that mirrors the
    # source line and therefore cannot fail.
    assert "unknown" in _SNAPSHOT_IN_FLIGHT, sorted(_SNAPSHOT_IN_FLIGHT)
    silent = []
    for status in PHASE_STATUSES:
        if status in _SNAPSHOT_DONE or status == "unplanned":
            continue
        if not phase_status_disagreements({"P": status}, [_entry("P", "completed")]):
            silent.append(status)
    assert silent == [], f"snapshot statuses silent against manifest 'completed': {silent}"


# ---------------------------------------------------------------------------
# ah#832 r6 (codex, BLOCKING): the file arm bypassed the ambiguity rule.
#
# The alias rule refuses to guess a roadmap from a contested ALIAS. The file arm,
# added two rounds later, then guessed one from a contested FILE — and a legacy
# record whose roadmap is genuinely unknowable SUPPRESSED a real disagreement.
# Both directions, as the seat asked, because the attributable set governs both.


def test_a_legacy_record_on_a_CONTESTED_file_settles_nothing():
    """Two roadmaps explicitly claim this file, so the legacy record could be either.

    Without the legacy record the v2 disagreement is reported. Adding a record whose
    roadmap is UNKNOWABLE made it disappear — the detector went silent on the strength of
    a tie it resolved by picking whichever side happened to be in scope. A silent
    detector is undetectable, which this file's own bar rates worse than a false positive.
    """
    contested = [
        _rec("P", "committed", "v2", _A),    # in scope, in flight
        _rec("P", "completed", "v1", _A),    # ANOTHER roadmap claims the same file
        _rec("P", "completed", None, _A),    # legacy: could belong to EITHER
    ]
    # The control first: without the legacy record, the disagreement is reported.
    assert phase_status_disagreements(
        {"P": "complete"}, contested[:2], roadmap_slug="v2"
    ) == [("P", "complete", "committed")]
    # ...and adding the unknowable record must not change that.
    assert phase_status_disagreements(
        {"P": "complete"}, contested, roadmap_slug="v2"
    ) == [("P", "complete", "committed")]


def test_a_legacy_record_on_a_CONTESTED_file_is_not_the_subject_either():
    """The OTHER direction, which the seat asked for explicitly.

    Attribution is one set governing both comparisons, so a record that cannot settle a
    phase must not be able to BE the subject of one. Before the fix this reported
    ('P','executing','completed') on the strength of that same unknowable record — the
    mirror-image error, and it would have named a phase from a roadmap we cannot identify
    as contradicting the active one.
    """
    contested = [
        _rec("P", "committed", "v2", _A),
        _rec("P", "completed", "v1", _A),
        _rec("P", "completed", None, _A),
    ]
    assert phase_status_disagreements({"P": "executing"}, contested, roadmap_slug="v2") == []


def test_CONTESTED_counts_distinct_ROADMAPS_not_records():
    """The superseded-plan shape must keep settling, or r1 comes back.

    Several records of the SAME roadmap naming one file is ordinary — that is exactly r1's
    superseded plan. Only a file claimed by more than one DISTINCT explicit slug is
    contested. Keying on record count instead would silence every settled phase that had
    ever been re-planned.
    """
    same_roadmap_twice = [
        _rec("P", "committed", "v2", _A),
        _rec("P", "executing", "v2", _A),
        _rec("P", "completed", None, _A),   # legacy, same file, NOT contested
    ]
    assert phase_status_disagreements(
        {"P": "complete"}, same_roadmap_twice, roadmap_slug="v2"
    ) == []


def test_manifest_done_vs_snapshot_PLANNED_is_reported():
    """The one in-flight member with no behavioural pin of its own.

    Five of the six had a dedicated test; `planned` appeared only in a test asserting
    SILENCE against an unstarted plan, so nothing would notice it being silenced against
    a manifest `completed`. It was in the originally shipped literal, which makes it a
    published guarantee rather than a new surface.

    Production shape: a repo whose `.phase-loop/state.json` is absent or stale — a fresh
    clone, a reset, a worktree that never ran the phase — classifies a phase that HAS a
    plan artifact as `planned` (classifier.py), while `plans/manifest.json` records it
    `completed`. That is the ah#312 harm class, not a corner case. (ah#832 r7, fable.)
    """
    assert phase_status_disagreements({"P": "planned"}, [_entry("P", "completed")]) == [
        ("P", "planned", "completed")
    ]


# ---------------------------------------------------------------------------
# ah#832 r7 (fable, BLOCKING): r5's defect on the SIBLING field.
#
# `_ref_from_json` does `slug=str(data.get("slug", ""))`, so a `roadmap_ref` that
# is present but names nothing arrives as `""` or the literal `"None"` — never as
# the object both consumers tested for. These cases CANNOT be reached with a
# hand-built DotfilesPlanRef, so they are driven through `read_manifest` on a real
# manifest file, which is the only way the coercion happens.


def _manifest_with_ref(tmp_path, ref, *, status="completed", alias="ALPHA"):
    """A real plans/manifest.json read back through the real parser."""
    import json
    from phase_loop_runtime.plan_manifest import SCHEMA_VERSION, read_manifest

    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    entry = {
        "slug": f"v1-{alias}", "file": f"plans/phase-plan-v1-{alias}.md", "type": "phase",
        "status": status, "created_at": "t", "updated_at": "t",
        "owner_skill": "codex-plan-phase", "phase_alias": alias,
    }
    if ref != "OMIT":
        entry["roadmap_ref"] = ref
    (tmp_path / "plans" / "manifest.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "plans": [entry]})
    )
    return read_manifest(tmp_path).plans


@pytest.mark.parametrize(
    "label,ref",
    [
        ("no roadmap_ref key at all", "OMIT"),
        ("roadmap_ref: null (the documented legacy shape)", None),
        ("roadmap_ref: {}", {}),
        ("roadmap_ref.slug: null", {"slug": None, "file": "specs/v1.md", "type": "phase", "status": "imported"}),
        ("roadmap_ref with no slug key", {"file": "specs/v1.md", "type": "phase", "status": "imported"}),
        ("roadmap_ref.slug: whitespace", {"slug": "   ", "file": "specs/v1.md", "type": "phase", "status": "imported"}),
    ],
)
def test_a_roadmap_ref_that_NAMES_NOTHING_is_not_read_as_a_FOREIGN_roadmap(tmp_path, label, ref):
    """Each of these silenced the flagship ah#312 case, on a manifest the validator accepts.

    Reading "names nothing" as "names another roadmap" denied the record BOTH routes at
    once — `in_scope` False and `claims_a_roadmap` True, which also closes the file arm —
    so the phase was reported by nobody. `_validate_phase_entry` never requires a slug
    key or a non-empty slug, so these shapes are affirmatively accepted rather than
    merely unvalidated on the render path.
    """
    entries = _manifest_with_ref(tmp_path, ref)
    assert phase_status_disagreements(
        {"ALPHA": "executing"}, entries, roadmap_slug="v1"
    ) == [("ALPHA", "executing", "completed")], label


def test_a_ref_naming_a_REAL_OTHER_roadmap_is_still_out_of_scope(tmp_path):
    """The control the normaliser must not break.

    Normalising absence must not normalise a genuine foreign claim. If this ever reports,
    the fix has become r2's false negative.
    """
    entries = _manifest_with_ref(
        tmp_path, {"slug": "OTHER", "file": "specs/OTHER.md", "type": "phase", "status": "imported"}
    )
    assert phase_status_disagreements({"ALPHA": "executing"}, entries, roadmap_slug="v1") == []


# ---------------------------------------------------------------------------
# ah#832 r7, class sweep. Three rounds running, every blocking finding has been
# one instance of ONE class: a value the parser can produce that a guard does not
# handle. `file` was r5, `slug` was r7 F1. So the remaining two fields the
# detector consumes were swept rather than waited for.


@pytest.mark.parametrize(
    "label,alias",
    [
        ("a list", ["A"]),
        ("a dict", {"a": 1}),
        ("a number", 123),
        ("null", None),
        ("empty string", ""),
        ("empty list (falsy — was already skipped)", []),
        ("empty dict (falsy — was already skipped)", {}),
    ],
)
def test_a_malformed_phase_alias_does_not_SILENCE_THE_WHOLE_detector(tmp_path, label, alias):
    """One bad entry must not disable the detector for every OTHER phase.

    `_entry_from_json` does `phase_alias=data.get("phase_alias")` with no coercion, so
    this field arrives exactly as written. A TRUTHY UNHASHABLE value got past the `if a:`
    test and `_alias_counts.get(a, 0)` then raised `TypeError: unhashable type: 'list'` —
    and `render.py` wraps reconciliation in `except Exception: return []`, so that
    TypeError became total silence for EVERY phase, not just the malformed record. One
    hand-edited entry disabled the whole detector, invisibly.

    `[]` and `{}` are falsy and were already skipped, which is why this never surfaced.
    The assertion is therefore about the OTHER phase: ALPHA must still be reported with
    the malformed sibling present.
    """
    import json
    from phase_loop_runtime.plan_manifest import SCHEMA_VERSION, read_manifest

    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    base = {
        "slug": "v1-ALPHA", "file": "plans/phase-plan-v1-ALPHA.md", "type": "phase",
        "status": "completed", "created_at": "t", "updated_at": "t",
        "owner_skill": "codex-plan-phase", "phase_alias": "ALPHA",
    }
    malformed = dict(base, slug="v1-BAD", file="plans/phase-plan-v1-BAD.md", phase_alias=alias)
    (tmp_path / "plans" / "manifest.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "plans": [base, malformed]})
    )
    entries = read_manifest(tmp_path).plans
    assert phase_status_disagreements({"ALPHA": "executing"}, entries) == [
        ("ALPHA", "executing", "completed")
    ], label


@pytest.mark.parametrize("status", ["", "None", "complete", "draft"])
def test_an_UNRECOGNISED_manifest_status_is_INERT_and_that_is_the_judgement(status):
    """Pinned as a DECISION, not discovered later as a defect.

    The same coercion exists here — `_entry_from_json` does
    `status=str(data.get("status", ""))`, so an absent key becomes `""` and an explicit
    null the literal `"None"` — and `"complete"` is the typo of `"completed"` that this
    vocabulary invites. None of them is in `_MANIFEST_DONE` or `_MANIFEST_IN_FLIGHT`, so
    such a record can neither settle a phase nor be reported.

    That is DELIBERATE, and it is where this field differs from `slug`. A coerced `slug`
    caused a WRONG classification — "names nothing" was read as "names another roadmap",
    which is a determinate error with a determinate fix. An uninterpretable STATUS is
    genuinely unknown: reporting `status='executing' vs manifest='draft'` would assert a
    contradiction between two things that might well agree, which is the false positive
    r1 shipped and this detector's declared scope ("only a DONE-vs-IN-FLIGHT pair is a
    contradiction") exists to prevent.

    The cost is real and stated plainly: a manifest whose `status` key is missing, or
    misspelled `complete`, will not settle a phase and will not be reported — so a true
    ah#312 disagreement written with a typo stays silent.

    AND THE BOUND ON THAT COST IS WEAKER THAN THIS DOCSTRING FIRST CLAIMED. It said
    "`validate_manifest` rejects those statuses, and that is the correct layer for a
    vocabulary error." Architecturally right, but **the public `validate_manifest` has no
    caller in `src/` at all** — only tests and the per-phase acceptance commands in
    `plans/phase-plan-v10-*.md` invoke it; `_validate_manifest_data` is the only internal
    user. So a misspelled status is silent on every operator surface today, not caught one
    layer up. The disposition stands — naming `manifest='draft'` as a contradiction
    asserts a disagreement between two things that may well agree — but this is a genuine
    gap rather than a covered one. (ah#832 r7; bound corrected r8, fable NB2.)
    """
    assert phase_status_disagreements({"P": "executing"}, [_entry("P", status)]) == []
    assert phase_status_disagreements({"P": "complete"}, [_entry("P", status)]) == []


# ---------------------------------------------------------------------------
# ah#832 r8 (fable, BLOCKING): A13 was FALSE as written.
#
# The r8 sweep closed the arm where the parser TOLERATES a value and a guard
# raises (`phase_alias`). This is the other arm: the parser itself REJECTS the
# row, and `read_manifest` is all-or-nothing, so one unparseable sibling row
# raised and `render.py`'s bare `except` deleted the entire report. Same class
# ah#164 already closed for discovery — the CHANGELOG names these exact shapes —
# and this read path was left on `read_manifest`.

_GOOD_ROW = {
    "slug": "v1-ALPHA", "file": "plans/phase-plan-v1-ALPHA.md", "type": "phase",
    "status": "completed", "created_at": "t", "updated_at": "t",
    "owner_skill": "codex-plan-phase", "phase_alias": "ALPHA",
}


def _write_manifest(tmp_path, rows):
    import json
    from phase_loop_runtime.plan_manifest import SCHEMA_VERSION

    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plans" / "manifest.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "plans": rows})
    )


def _real_render_path(tmp_path, monkeypatch):
    """`render._manifest_disagreements` on a real snapshot and a real manifest file.

    Not the helper: the defect lived in the LOAD, so a test that hands entries straight
    to `phase_status_disagreements` cannot see it at all.
    """
    from phase_loop_runtime import render

    class _Snap:
        repo = str(tmp_path)
        roadmap = "specs/phase-plans-v1.md"
        phases = {"ALPHA": "executing"}

    clashes, _complete = render._manifest_disagreements(_Snap())
    return clashes


@pytest.mark.parametrize(
    "label,sibling",
    [
        ("roadmap_ref is a string", dict(_GOOD_ROW, slug="b", file="plans/b.md", roadmap_ref="a string")),
        ("roadmap_ref is a list", dict(_GOOD_ROW, slug="c", file="plans/c.md", roadmap_ref=["x"])),
        ("the entry is not an object", "not an object"),
        ("a lifecycle event is not an object", dict(_GOOD_ROW, slug="d", file="plans/d.md", lifecycle=["nope"])),
        ("lifecycle metadata is not an object",
         dict(_GOOD_ROW, slug="e", file="plans/e.md",
              lifecycle=[{"transition": "imported", "by": "x", "at": "t", "metadata": "nope"}])),
    ],
)
def test_a_parse_hostile_SIBLING_row_does_not_delete_an_EXPLICITLY_CLAIMED_report(
    tmp_path, monkeypatch, label, sibling
):
    """An unparseable row must not delete the signal of a record that STATES its roadmap.

    Each of these raised inside `read_manifest`, and the bare `except` at
    `render._manifest_disagreements` turned that into total silence — with a genuine
    `ALPHA: executing` vs manifest `completed` disagreement sitting right beside it.
    Measured on the real render path, which is the only place that defect is visible.

    THE r8 VERSION OF THIS TEST ASSERTED A STRONGER GUARANTEE THAN IS SOUND. It used a
    record with NO `roadmap_ref` and required it to report anyway. r9 proved that exact
    shape misleading: with a row skipped, the alias-ambiguity census is incomplete, so
    admitting a no-claim record reports a phase that may belong to another roadmap. The
    guarantee that survives — and the one worth having — is about records that do not
    rest on absence at all: an EXPLICIT claim is still honoured beside an unparseable
    sibling. The no-claim case is pinned as a refusal directly below. (ah#832 r9.)
    """
    claimed = dict(_GOOD_ROW, roadmap_ref={
        "slug": "phase-plans-v1", "file": "specs/phase-plans-v1.md",
        "type": "phase", "status": "imported",
    })
    _write_manifest(tmp_path, [claimed, sibling])
    assert _real_render_path(tmp_path, monkeypatch) == [
        ("ALPHA", "executing", "completed")
    ], label


@pytest.mark.parametrize(
    "label,sibling",
    [
        ("roadmap_ref is a string", dict(_GOOD_ROW, slug="b", file="plans/b.md", roadmap_ref="a string")),
        ("the entry is not an object", "not an object"),
    ],
)
def test_a_NO_CLAIM_record_is_REFUSED_while_a_row_is_unparseable(tmp_path, monkeypatch, label, sibling):
    """The conservative half, and the r9 finding stated as a property.

    A record with no `roadmap_ref` is attributed only because its alias looks
    unambiguous — and that census is computed over the rows the detector was HANDED, so a
    skipped sibling makes an ambiguous alias look unambiguous. Reporting on that basis is
    what `in_scope` calls "actively misleading": the phase may belong to another roadmap
    entirely. With the manifest fully parsed the same record reports (the control below),
    so this is a refusal caused by missing evidence, not a silenced detector.
    """
    _write_manifest(tmp_path, [_GOOD_ROW, sibling])
    assert _real_render_path(tmp_path, monkeypatch) == [], label


def test_the_same_NO_CLAIM_record_DOES_report_when_every_row_parses(tmp_path, monkeypatch):
    """The control that keeps the refusal above honest.

    Without it, the refusal test would pass against a detector that had simply stopped
    reporting no-claim records altogether.
    """
    _write_manifest(tmp_path, [_GOOD_ROW])
    assert _real_render_path(tmp_path, monkeypatch) == [("ALPHA", "executing", "completed")]


@pytest.mark.parametrize(
    "label,payload",
    [
        ("plans is not an array", {"plans": "nope"}),
        ("unsupported schema_version", {"schema_version": 99}),
        ("the manifest is not an object", None),
    ],
)
def test_a_STRUCTURAL_failure_still_hides_the_WHOLE_manifest(tmp_path, label, payload):
    """The ah#164 disposition, kept deliberately: nothing in the file is trustworthy.

    Only ROW-level parse failures are skipped. A structural failure must still refuse,
    or a corrupt manifest would be read as a partially-valid one — which is the
    fabricated-partial-read trade the broker stores refuse for the same reason.
    """
    import json
    from phase_loop_runtime.plan_manifest import SCHEMA_VERSION, parseable_plan_entries

    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    body = ["nope"] if payload is None else {"schema_version": SCHEMA_VERSION, "plans": [_GOOD_ROW], **payload}
    (tmp_path / "plans" / "manifest.json").write_text(json.dumps(body))
    with pytest.raises(ValueError):
        parseable_plan_entries(tmp_path)


def test_a_RENAMED_plan_file_is_still_reported(tmp_path):
    """Why this is not `valid_phase_entries`, which the ah#164 fix used.

    That helper materializes only rows that VALIDATE, and validation checks the plan file
    exists on disk. Measured: with the plan file absent, `valid_phase_entries` yields 0
    entries where the per-row parse yields 1. Dropping it would introduce a NEW silence
    in the detector whose whole purpose is to report disagreements — whether the file was
    renamed is not the question being asked, and it is not a reason to stop saying the two
    stores disagree about the phase. (ah#832 r8.)
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries, valid_phase_entries

    _write_manifest(tmp_path, [_GOOD_ROW])  # note: the plan FILE is never created
    assert len(parseable_plan_entries(tmp_path).entries) == 1
    dropped = valid_phase_entries(tmp_path / "plans" / "manifest.json")
    assert dropped is not None and len(dropped) == 0, dropped
    assert phase_status_disagreements(
        {"ALPHA": "executing"}, parseable_plan_entries(tmp_path).entries
    ) == [("ALPHA", "executing", "completed")]


# ---------------------------------------------------------------------------
# ah#832 r8 (codex, BLOCKING): the r7 F1 normaliser discarded the roadmap
# identity carried in `roadmap_ref.file`. The production consumer identifies the
# active roadmap as `Path(snapshot.roadmap).stem` (render.py:458), so a ref naming
# `specs/v1.md` with no slug DOES reference v1. Reading it as "names nothing" let
# it through the file arm and settle a different roadmap's phase — r2's
# foreign-roadmap false negative, reintroduced by the fix for F1.


def _ref(slug=None, file=None):
    if slug is None and file is None:
        return None
    return DotfilesPlanRef(slug=slug or "", file=file or "", type="phase", status="imported")


def _rec_ref(alias, status, ref, file):
    return DotfilesPlanEntry(
        slug=f"{status}-{file}-{id(ref)}", file=file, type="phase", status=status,
        created_at="t", updated_at="t", owner_skill="codex-plan-phase",
        phase_alias=alias, roadmap_ref=ref,
    )


def test_a_slugless_ref_that_names_a_FOREIGN_roadmap_by_FILE_settles_nothing():
    """codex's case: the record references v1 through its ref file, so v2 must report."""
    entries = [
        _rec_ref("P", "committed", _ref("v2", "specs/v2.md"), _A),
        _rec_ref("P", "completed", _ref(None, "specs/v1.md"), _A),
    ]
    assert phase_status_disagreements({"P": "complete"}, entries, roadmap_slug="v2") == [
        ("P", "complete", "committed")
    ]


def test_a_slugless_ref_naming_a_FOREIGN_roadmap_is_not_the_subject_either():
    """The other direction the seat asked for: it must not BE the reported disagreement."""
    entries = [
        _rec_ref("P", "committed", _ref("v2", "specs/v2.md"), _A),
        _rec_ref("P", "completed", _ref(None, "specs/v1.md"), _A),
    ]
    assert phase_status_disagreements({"P": "executing"}, entries, roadmap_slug="v2") == []


def test_a_slugless_ref_naming_the_ACTIVE_roadmap_by_file_IS_in_scope():
    """The control that stops the fallback becoming a blanket exclusion.

    Same stem rule as the consumer, so a ref naming `specs/v2.md` is the active roadmap
    whether or not the slug survived whatever wrote it.
    """
    entries = [_rec_ref("P", "completed", _ref(None, "specs/v2.md"), _A)]
    assert phase_status_disagreements({"P": "executing"}, entries, roadmap_slug="v2") == [
        ("P", "executing", "completed")
    ]


def test_a_ref_that_names_NOTHING_AT_ALL_is_still_legacy():
    """r7's F1 fix must survive r8's: `roadmap_ref: {}` claims nothing by slug OR file."""
    empty = DotfilesPlanRef(slug="", file="", type="", status="")
    assert phase_status_disagreements(
        {"P": "executing"}, [_rec_ref("P", "completed", empty, _A)], roadmap_slug="v2"
    ) == [("P", "executing", "completed")]
    assert _roadmap_claim(_rec_ref("P", "completed", empty, _A)) is None
    assert _roadmap_claim(_rec_ref("P", "completed", None, _A)) is None


# ---------------------------------------------------------------------------
# ah#832 r9 (fable F2, BLOCKING): the SIXTH surface — entry `type`.
#
# The class table claimed five surfaces. `type` was never checked, so a
# `type: "detailed"` row carrying a `phase_alias` was attributed like a phase
# plan. `validate_manifest` calls all of these structurally valid, and the
# per-entry rule that would reject them sits behind a validator with no `src/`
# caller — so it is not covered one layer up.


def _detailed(alias="ALPHA", status="completed", file="plans/detailed-x.md", slug=None):
    entry = {
        "slug": f"d-{status}-{file}", "file": file, "type": "detailed", "status": status,
        "created_at": "t", "updated_at": "t", "owner_skill": "x", "phase_alias": alias,
    }
    if slug:
        entry["roadmap_ref"] = {"slug": slug, "file": f"specs/{slug}.md",
                                "type": "phase", "status": "imported"}
    return entry


def _phase_row(status, file="plans/phase-plan-A.md", alias="ALPHA", slug="v2"):
    return {
        "slug": f"p-{status}-{file}", "file": file, "type": "phase", "status": status,
        "created_at": "t", "updated_at": "t", "owner_skill": "x", "phase_alias": alias,
        "roadmap_ref": {"slug": slug, "file": f"specs/{slug}.md",
                        "type": "phase", "status": "imported"},
    }


def _detect(tmp_path, rows, snapshot="complete"):
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    _write_manifest(tmp_path, rows)
    parsed = parseable_plan_entries(tmp_path)
    return phase_status_disagreements(
        {"ALPHA": snapshot}, parsed.entries, roadmap_slug="v2",
        attribution_evidence_complete=parsed.skipped == 0,
    )


@pytest.mark.parametrize(
    "label,detailed_row",
    [
        ("claiming the active roadmap", _detailed(slug="v2")),
        ("on the SAME plan file", _detailed(file="plans/phase-plan-A.md")),
        ("with no claim at all", _detailed()),
    ],
)
def test_a_type_DETAILED_row_does_not_speak_for_a_PHASE(tmp_path, label, detailed_row):
    """A detailed row must not settle a phase it happens to carry the alias of.

    Measured before the fix: the first two shapes SILENCED a genuine
    `('ALPHA','complete','committed')` disagreement.
    """
    assert _detect(tmp_path, [_phase_row("committed"), detailed_row]) == [
        ("ALPHA", "complete", "committed")
    ], label


def test_a_type_DETAILED_row_cannot_BE_the_subject_either(tmp_path):
    """The other direction: before the fix a lone detailed row was reported as the phase."""
    assert _detect(tmp_path, [_detailed(slug="v2")], snapshot="executing") == []


def test_a_real_PHASE_sibling_still_settles(tmp_path):
    """The control: the `type` filter must not stop real phase rows from settling."""
    assert _detect(tmp_path, [
        _phase_row("committed"), _phase_row("completed", file="plans/phase-plan-B.md"),
    ]) == []


def test_a_skipped_FOREIGN_claimant_does_not_uncontest_a_file(tmp_path):
    """codex's r9 case: corrupting one row's UNRELATED metadata suppressed another's signal.

    Three rows share alias `P` and plan file A: an in-scope `v2 committed`, a foreign
    `v1 failed`, and a legacy `completed` with no claim. With all three parsed the file is
    CONTESTED, the legacy record is refused, and the v2 disagreement reports. Make the v1
    row parse-hostile in a way that has nothing to do with its roadmap claim — a
    non-object `lifecycle` — and the r8 loader skipped it, the file looked uncontested,
    the legacy `completed` became attributable and SETTLED the phase. The disagreement
    vanished because an unrelated field in a different row was corrupt.

    That is the precise inverse of the loader's r8 claim that one unparseable row costs
    only its own signal. (ah#832 r9, codex.)
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    A = "plans/phase-plan-A.md"
    def row(status, slug, **extra):
        entry = {
            "slug": f"{status}-{slug}", "file": A, "type": "phase", "status": status,
            "created_at": "t", "updated_at": "t", "owner_skill": "x", "phase_alias": "P",
        }
        if slug:
            entry["roadmap_ref"] = {"slug": slug, "file": f"specs/{slug}.md",
                                    "type": "phase", "status": "imported"}
        entry.update(extra)
        return entry

    intact = [row("committed", "v2"), row("failed", "v1"), row("completed", None)]
    hostile = [row("committed", "v2"), row("failed", "v1", lifecycle=["nope"]),
               row("completed", None)]
    expected = [("P", "complete", "committed")]

    for label, rows in (("all rows parse", intact), ("the v1 row is parse-hostile", hostile)):
        _write_manifest(tmp_path, rows)
        parsed = parseable_plan_entries(tmp_path)
        assert phase_status_disagreements(
            {"P": "complete"}, parsed.entries, roadmap_slug="v2",
            attribution_evidence_complete=parsed.skipped == 0,
        ) == expected, label


def test_a_DETAILED_row_does_not_make_an_alias_look_AMBIGUOUS(tmp_path):
    """The census must agree with attribution about who speaks, in BOTH directions.

    The `type` filter on attribution stops a detailed row settling a phase. The same
    filter on the alias census stops it causing the opposite harm: counting a detailed
    row toward ambiguity makes a single legacy phase row look contested, so the legacy
    record is REFUSED and a real disagreement goes silent. One phase row and one detailed
    row sharing the alias is the case that crosses the 1-to-2 boundary, and it is the only
    shape where the two censuses can be told apart. (ah#832 r9.)
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    legacy_only = {
        "slug": "p-legacy", "file": "plans/phase-plan-A.md", "type": "phase",
        "status": "completed", "created_at": "t", "updated_at": "t",
        "owner_skill": "x", "phase_alias": "ALPHA",
    }
    _write_manifest(tmp_path, [legacy_only, _detailed(alias="ALPHA", status="committed")])
    parsed = parseable_plan_entries(tmp_path)
    assert phase_status_disagreements(
        {"ALPHA": "executing"}, parsed.entries, roadmap_slug="v2",
        attribution_evidence_complete=parsed.skipped == 0,
    ) == [("ALPHA", "executing", "completed")]


# ---------------------------------------------------------------------------
# ah#832 r10 (fable B1/NB1): the r9 refusal was too broad in one direction and
# undocumented in another.


def test_a_skipped_NON_PHASE_row_does_not_disarm_the_guessing_arms(tmp_path):
    """A `detailed` row cannot have entered any census, so losing it changes nothing.

    r9's own `type` filter is what makes this provable: `_alias_counts` skips non-phase
    rows, and `scoped_files`, `claimed_by` and `contested_files` are all built from `own`,
    which filters `type == "phase"`. Counting a skipped `detailed` row disabled both
    guessing arms for every phase — measured on this repo's real 58-row manifest (21 of
    them `detailed`), one hostile detailed row took the report from 12 phases to 6, and
    the six lost were exactly its six legacy `roadmap_ref: null` rows.
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    legacy = {
        "slug": "p-legacy", "file": "plans/phase-plan-A.md", "type": "phase",
        "status": "completed", "created_at": "t", "updated_at": "t",
        "owner_skill": "x", "phase_alias": "ALPHA",
    }
    hostile_detailed = {
        "slug": "d-hostile", "file": "plans/detailed-x.md", "type": "detailed",
        "status": "committed", "created_at": "t", "updated_at": "t", "owner_skill": "x",
        "lifecycle": [{"transition": "imported", "by": "x", "at": "t", "metadata": "nope"}],
    }
    _write_manifest(tmp_path, [legacy, hostile_detailed])
    parsed = parseable_plan_entries(tmp_path)
    assert parsed.skipped == 0, "a readably non-phase row must not count as lost evidence"
    assert phase_status_disagreements(
        {"ALPHA": "executing"}, parsed.entries, roadmap_slug="v2",
        attribution_evidence_complete=parsed.skipped == 0,
    ) == [("ALPHA", "executing", "completed")]


@pytest.mark.parametrize(
    "label,hostile",
    [
        ("a PHASE row", {"slug": "p-h", "file": "plans/p.md", "type": "phase",
                         "status": "committed", "created_at": "t", "updated_at": "t",
                         "owner_skill": "x", "phase_alias": "ZZZ", "roadmap_ref": "a string"}),
        ("an unreadable row", "not an object"),
        ("a row whose type is not a string", {"slug": "x", "file": "plans/x.md", "type": 7,
                                              "status": "committed", "created_at": "t",
                                              "updated_at": "t", "owner_skill": "x",
                                              "roadmap_ref": "a string"}),
    ],
)
def test_a_skipped_row_that_MIGHT_have_been_a_phase_row_still_disarms(tmp_path, label, hostile):
    """The control: the exemption is narrow, and an unreadable `type` is not an exemption.

    Without this, the fix above would read as "skipped rows no longer matter", which is
    the r9 defect restored.
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    legacy = {
        "slug": "p-legacy", "file": "plans/phase-plan-A.md", "type": "phase",
        "status": "completed", "created_at": "t", "updated_at": "t",
        "owner_skill": "x", "phase_alias": "ALPHA",
    }
    _write_manifest(tmp_path, [legacy, hostile])
    parsed = parseable_plan_entries(tmp_path)
    assert parsed.skipped == 1, label
    assert phase_status_disagreements(
        {"ALPHA": "executing"}, parsed.entries, roadmap_slug="v2",
        attribution_evidence_complete=parsed.skipped == 0,
    ) == [], label


def test_a_SETTLED_phase_REPORTS_when_evidence_is_incomplete_a_KNOWN_trade(tmp_path):
    """NB1: the half the r9 docstring left out, now stated and pinned.

    The r9 note claimed only the reassuring half — "direct claims are unaffected". It is
    also true that a phase SETTLED by a same-file legacy record (the r1/r3/r4 case) starts
    REPORTING the moment any sibling row is unparseable, because the record that settled
    it is exactly the kind now refused. Fail-loud is the direction this module prefers and
    it follows from the same rule rather than being a separate decision — but it is a real
    behaviour change, and stating only the comfortable half is how a comment becomes a
    false claim. Twice on this PR already.
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    A = "plans/phase-plan-A.md"
    in_scope = {"slug": "p-v2", "file": A, "type": "phase", "status": "committed",
                "created_at": "t", "updated_at": "t", "owner_skill": "x",
                "phase_alias": "P",
                "roadmap_ref": {"slug": "v2", "file": "specs/v2.md",
                                "type": "phase", "status": "imported"}}
    settling_legacy = {"slug": "p-legacy", "file": A, "type": "phase", "status": "completed",
                       "created_at": "t", "updated_at": "t", "owner_skill": "x",
                       "phase_alias": "P"}
    hostile_phase = {"slug": "p-h", "file": "plans/p.md", "type": "phase",
                     "status": "committed", "created_at": "t", "updated_at": "t",
                     "owner_skill": "x", "phase_alias": "ZZZ", "roadmap_ref": "a string"}

    def detect(rows):
        _write_manifest(tmp_path, rows)
        parsed = parseable_plan_entries(tmp_path)
        return phase_status_disagreements(
            {"P": "complete"}, parsed.entries, roadmap_slug="v2",
            attribution_evidence_complete=parsed.skipped == 0,
        )

    assert detect([in_scope, settling_legacy]) == [], "settled while every row parses"
    # ...and it REPORTS once a row is lost. That is a KNOWN false positive, not an
    # oversight, and it is the side of a trade that cannot be won: r9's codex finding
    # requires reporting here (a dropped foreign row must not let a legacy record suppress
    # a real disagreement) and r10's codex finding requires silence (a dropped in-scope
    # `completed` row must not produce a false report). The two are structurally identical
    # from inside the detector — a phase row is missing, its identity unknowable — and
    # implementing the r10 refusal turned the r9 regression test red, which is that
    # finding returning. The tie breaks on this module's recorded bar: silence is worse
    # than a false positive here. The operator sees a settled phase AND an unreadable
    # manifest row, which is worth knowing.
    assert detect([in_scope, settling_legacy, hostile_phase]) == [("P", "complete", "committed")]


def test_an_UNUSABLE_alias_counts_as_incomplete_evidence(tmp_path):
    """r10 codex #2: a row that PARSES but is unusable is lost evidence too.

    `skipped` counts rows the parser rejected. A phase row whose `phase_alias` is not a
    usable string parses fine — so `skipped` stays 0 — and is then dropped by every census
    and by attribution, which is indistinguishable from never having been there. Measured:
    `v2 committed` + `v1 failed` + legacy `completed` on one file correctly reports the v2
    disagreement; change the foreign row's alias to `["P"]` and the file looked
    uncontested, the legacy record settled, and the report vanished.
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    A = "plans/phase-plan-A.md"
    def row(status, slug, alias="P"):
        e = {"slug": f"{status}-{slug}", "file": A, "type": "phase", "status": status,
             "created_at": "t", "updated_at": "t", "owner_skill": "x", "phase_alias": alias}
        if slug:
            e["roadmap_ref"] = {"slug": slug, "file": f"specs/{slug}.md",
                                "type": "phase", "status": "imported"}
        return e

    for label, foreign_alias in (("a list", ["P"]), ("a number", 7), ("empty", ""), ("null", None)):
        _write_manifest(tmp_path, [row("committed", "v2"),
                                   row("failed", "v1", alias=foreign_alias),
                                   row("completed", None)])
        parsed = parseable_plan_entries(tmp_path)
        # r10 asserted `skipped == 0` here, because the row PARSES and the rule then
        # lived in the detector. r11 moved the rule to the LOADER — the only place that
        # can still see raw `type` and `file` before `str()` coercion makes garbage look
        # readable — so a parsed-but-unusable row is counted as lost evidence there.
        # Same outcome for the detector, better place for the judgement.
        assert parsed.skipped == 1, f"{label}: unusable identity is lost evidence"
        assert phase_status_disagreements(
            {"P": "complete"}, parsed.entries, roadmap_slug="v2",
            attribution_evidence_complete=parsed.skipped == 0,
        ) == [("P", "complete", "committed")], label


# ---------------------------------------------------------------------------
# ah#832 r11: ONE field-general lost-evidence rule, and the completeness test
# that makes "have we swept the class?" answerable by EXECUTION.


# ITERATE THE TUPLE, DO NOT HAND-LIST IT. The first version of this decorator named the
# three fields literally — which is the very drift this test exists to prevent, and the
# matrix caught it the moment `roadmap_ref.*` was added to the tuple and nothing new ran.
# BOTH POSITIONS. The r11 sweep varied ONE row of a three-row fixture and called the
# result a class sweep — the r12 seat identified that as its own method error. A field is
# only swept when it is corrupted in the row under judgement (SUBJECT) as well as in the
# competing row (FOREIGN): the two positions reach different code, and r12's blocking
# finding lived in the one the sweep did not vary.
@pytest.mark.parametrize("position", ["foreign", "subject"])
@pytest.mark.parametrize("field", _CENSUS_IDENTITY_FIELDS)
@pytest.mark.parametrize(
    "unreadable", [None, ["x"], {"a": 1}, 123, "", "   "], ids=lambda v: repr(v)[:12]
)
def test_EVERY_census_identity_field_is_lost_evidence_when_unreadable(
    tmp_path, field, position, unreadable
):
    """The closure criterion the r11 seat named, executable.

    r5 fixed `file`, r7 fixed `slug`, r8 fixed `phase_alias`, r10 fixed the
    parses-but-unusable case for `phase_alias` ALONE — and r11 showed `type` and `file`
    had the same hole, worse, because the parser's `str()` coercion makes a garbage value
    look readable (`["plans/x.md"]` becomes `"['plans/x.md']"`). Three rounds of
    field-specific fixes each left the next field open.

    This iterates `_CENSUS_IDENTITY_FIELDS` rather than listing cases, so a field added to
    that tuple is covered here whether or not anyone remembers this test, and a field
    REMOVED from the rule fails it. That is what makes the sweep a measurement instead of
    a claim.

    The scenario is codex's: three rows on one file, `v2 committed` + `v1 failed` +
    legacy `completed`, snapshot `complete`. Corrupt only the FOREIGN row's identity and
    its claim silently vanishes from the contested-file census — so the file looks
    uncontested, the legacy record settles, and a real v2 disagreement is suppressed
    unless that row is counted as lost evidence.
    """
    from phase_loop_runtime.plan_manifest import _CENSUS_IDENTITY_FIELDS, parseable_plan_entries

    assert field in _CENSUS_IDENTITY_FIELDS

    A = "plans/phase-plan-A.md"
    def row(status, slug, **over):
        e = {"slug": f"{status}-{slug}", "file": A, "type": "phase", "status": status,
             "created_at": "t", "updated_at": "t", "owner_skill": "x", "phase_alias": "P"}
        if slug:
            e["roadmap_ref"] = {"slug": slug, "file": f"specs/{slug}.md",
                                "type": "phase", "status": "imported"}
        e.update(over)
        return e

    def corrupt(base):
        """Apply the unreadable value to `field` on a copy of `base`."""
        out = dict(base)
        if field.startswith("roadmap_ref."):
            leaf = field.split(".", 1)[1]
            ref = dict(out.get("roadmap_ref") or
                       {"slug": "v1", "file": "specs/v1.md", "type": "phase", "status": "imported"})
            ref[leaf] = unreadable
            out["roadmap_ref"] = ref
        else:
            out[field] = unreadable
        return out

    if field.startswith("roadmap_ref.") and (
        unreadable is None or (isinstance(unreadable, str) and not unreadable.strip())
    ):
        pytest.skip("absent or blank is the legacy ref spelling, not an unreadable identity")

    if position == "foreign":
        # The competing claimant is corrupted. Its claim vanishes from the contested-file
        # census, so the file looks uncontested, the legacy record settles, and a real v2
        # disagreement is suppressed unless the row counts as lost evidence.
        rows = [row("committed", "v2"), corrupt(row("failed", "v1")), row("completed", None)]
        control = [row("committed", "v2"), row("failed", "v1"), row("completed", None)]
        snapshot, expected = "complete", [("P", "complete", "committed")]
    else:
        # THE SUBJECT POSITION: the row that would BE the disagreement is corrupted — an
        # active-roadmap row with a status that can report. r13's seats found the previous
        # version reused the FOREIGN row here (`failed`, roadmap v1), which is neither, so
        # the branch re-asserted the foreign case under a second name and swept nothing.
        rows = [corrupt(row("completed", "v2"))]
        control = [row("completed", "v2")]
        snapshot = "executing"
        # WHAT THE SUBJECT SHOULD DO DEPENDS ON WHICH IDENTITY IS UNREADABLE, and saying
        # so here is the behavioural half of r13's criterion:
        #
        #   roadmap_ref.*  the claim could be MANUFACTURED by the `str()` coercion, and
        #                  `in_scope` grants a direct claim without consulting the
        #                  evidence flag — so the row is destroyed and cannot report.
        #   phase_alias    it cannot be attributed to any phase; nothing to report.
        #   type           `own` admits only `type == "phase"`, so it cannot speak.
        #   file           ITS CLAIM IS STILL READABLE. Only its FILE-census contribution
        #                  is lost, so it must STILL REPORT while counting as lost
        #                  evidence. Destroying it here was the r13 over-reach: a direct
        #                  claim no coercion invented was being thrown away.
        expected = [("P", "executing", "completed")] if field == "file" else []

    def detect(manifest_rows):
        _write_manifest(tmp_path, manifest_rows)
        parsed = parseable_plan_entries(tmp_path)
        return parsed.skipped, phase_status_disagreements(
            {"P": snapshot}, parsed.entries, roadmap_slug="v2",
            attribution_evidence_complete=parsed.skipped == 0,
        )

    # THE CONTROL FIRST, so a case that cannot fail is impossible: with every identity
    # readable this fixture must produce the OPPOSITE verdict. Without it, `expected == []`
    # in the subject position would pass against a detector that had stopped reporting
    # entirely. (r13, codex.)
    control_skipped, control_out = detect(control)
    assert control_skipped == 0, f"{position}/{field}: the control must be fully readable"
    if position == "foreign":
        assert control_out == expected, f"{position}/{field}: control"
    else:
        assert control_out == [("P", "executing", "completed")], (
            f"{position}/{field}: the readable subject must REPORT, or this case is vacuous"
        )

    skipped, out = detect(rows)
    assert skipped == 1, f"{position}/{field}={unreadable!r} must be lost evidence"
    assert out == expected, f"{position}/{field}={unreadable!r}"


def test_a_row_with_every_identity_field_READABLE_is_not_lost_evidence(tmp_path):
    """The control: the rule must not mark a well-formed manifest incomplete.

    Without this, the sweep above would pass against a loader that had simply started
    counting every row as lost — which disarms both guessing arms permanently.
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    A = "plans/phase-plan-A.md"
    rows = [
        {"slug": "p1", "file": A, "type": "phase", "status": "committed", "created_at": "t",
         "updated_at": "t", "owner_skill": "x", "phase_alias": "P",
         "roadmap_ref": {"slug": "v2", "file": "specs/v2.md", "type": "phase", "status": "imported"}},
        {"slug": "d1", "file": "plans/detailed-x.md", "type": "detailed", "status": "committed",
         "created_at": "t", "updated_at": "t", "owner_skill": "x"},
    ]
    _write_manifest(tmp_path, rows)
    assert parseable_plan_entries(tmp_path).skipped == 0


def test_the_status_surface_SAYS_the_reconciliation_is_incomplete(tmp_path, monkeypatch):
    """codex r11's third option: say INCOMPLETE rather than assert certainty.

    The header tells the operator "one of these is stale". When a manifest row could not
    be read that claims more than the evidence supports — a dropped row may have been the
    record that settled the phase. The choice was never only report-or-silence; the third
    option is in PRESENTATION, and it keeps the visible warning without asserting a
    confirmed contradiction. The seat also found that `skipped` reached no operator
    surface at all, so the consolation the r10 note offered ("the operator finds an
    unreadable manifest row") was not actually delivered. Now it is.
    """
    from phase_loop_runtime import render

    _write_manifest(tmp_path, [
        dict(_GOOD_ROW, roadmap_ref={"slug": "phase-plans-v1", "file": "specs/phase-plans-v1.md",
                                     "type": "phase", "status": "imported"}),
        "not an object",
    ])

    class _Snap:
        repo = str(tmp_path)
        roadmap = "specs/phase-plans-v1.md"
        phases = {"ALPHA": "executing"}

    lines = render._manifest_disagreement_lines(_Snap())
    assert any("ALPHA" in line for line in lines), lines
    assert any("INCOMPLETE" in line for line in lines), lines


def test_an_unreadable_ref_may_not_MANUFACTURE_a_claim_on_the_active_roadmap(tmp_path):
    """codex r12: a coerced slug that happens to EQUAL the active roadmap.

    This is the case the field sweep above cannot reach, because there the foreign row
    claims a different roadmap and a manufactured value simply fails to match. Here the
    coercion produces the active roadmap's own stem:

        "roadmap_ref": {"slug": 2026, "file": "specs/v1.md"}   ->  slug "2026"

    and the active roadmap IS `2026`. So the row is read as a POSITIVE DIRECT CLAIM
    despite its ref file naming a foreign roadmap — and direct attribution does not
    consult the incomplete-evidence flag at all, which is why merely counting the row as
    lost evidence is insufficient. It must not reach the detector: an identity that cannot
    be read may not manufacture a claim out of a coercion.
    """
    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    A = "plans/phase-plan-A.md"
    def row(status, ref):
        e = {"slug": f"{status}-{A}", "file": A, "type": "phase", "status": status,
             "created_at": "t", "updated_at": "t", "owner_skill": "x", "phase_alias": "P"}
        if ref is not None:
            e["roadmap_ref"] = ref
        return e

    _write_manifest(tmp_path, [
        row("committed", {"slug": "2026", "file": "specs/2026.md",
                          "type": "phase", "status": "imported"}),
        row("completed", {"slug": 2026, "file": "specs/v1.md",
                          "type": "phase", "status": "imported"}),
    ])
    parsed = parseable_plan_entries(tmp_path)
    assert parsed.skipped == 1, "an unreadable ref identity is lost evidence"
    assert all(getattr(e, "status", None) != "completed" for e in parsed.entries), \
        "the row must not reach the detector at all — it could manufacture a claim"
    assert phase_status_disagreements(
        {"P": "complete"}, parsed.entries, roadmap_slug="2026",
        attribution_evidence_complete=parsed.skipped == 0,
    ) == [("P", "complete", "committed")]


def test_this_REPOSITORYS_OWN_manifest_is_not_marked_incomplete():
    """The over-refusal guard, on real data rather than a fixture.

    Every round of this PR has tightened what counts as lost evidence, and each tightening
    risks the opposite failure: marking a well-formed manifest incomplete disarms both
    guessing arms permanently and silences the legacy population the arms exist to serve.
    A synthetic control cannot catch that, because I write the synthetic rows.

    This repository's own `plans/manifest.json` is the adversarial case available for free:
    58 rows, 21 of them `type: "detailed"`, 6 legacy `roadmap_ref: null`. If the rule ever
    starts refusing real shipped data, this fails. (ah#832 r12, fable probe 4.)

    THE GUARD'S CLAIM IS SCOPED TO THIS REPO, and that matters more than it reads. The r13
    seat ran the rule over 68 real `plans/manifest.json` files on its host: this one is
    clean, and ONE other is not — `pmcp`'s `phase-plan-v12-UPDPATH` carries
    `"type": "phase"` with `"phase_alias": null`, so a shipped writer demonstrably emits
    that shape. The refusal there is SOUND (a readable alias would have incremented
    `_alias_counts`, so losing it can flip an alias from ambiguous to unambiguous — r9's
    false-positive class) and its effect on that repo is bounded: the report is unchanged,
    because that row is its only legacy null-ref phase row. But on a repo that DOES carry a
    legacy population the cost is real — injecting that exact shape into this manifest takes
    the report from 9 phases to 8. Recorded so nobody reads a green test here as "the rule
    refuses nothing real". (ah#832 r13, fable NB1.)
    """
    from pathlib import Path

    from phase_loop_runtime.plan_manifest import parseable_plan_entries

    repo = Path(__file__).resolve().parents[2]
    if not (repo / "plans" / "manifest.json").exists():
        pytest.skip("not running inside the agent-harness checkout")
    parsed = parseable_plan_entries(repo)
    assert parsed.skipped == 0, (
        f"{parsed.skipped} row(s) of this repo's own manifest were called unreadable — "
        "the rule is over-refusing on real data"
    )
    assert len(parsed.entries) > 0


def test_the_status_PROSE_says_INCOMPLETE_even_with_nothing_else_to_print(tmp_path, monkeypatch):
    """NB1: the zero-clash case is the one that motivated the whole qualifier.

    If the row that could not be read IS the row that would have disagreed, there is
    nothing else to print — and the prose branch returned early, so `status` looked clean
    on a manifest it could not fully read. The JSON branch carried the flag
    unconditionally; the prose branch, which is what a human reads, did not. The existing
    test supplies a clash, so it never reached this path.
    """
    from phase_loop_runtime import render

    # A manifest with NO disagreement to report, and one unreadable row.
    _write_manifest(tmp_path, [
        dict(_GOOD_ROW, status="committed",
             roadmap_ref={"slug": "phase-plans-v1", "file": "specs/phase-plans-v1.md",
                          "type": "phase", "status": "imported"}),
        "not an object",
    ])

    class _Snap:
        repo = str(tmp_path)
        roadmap = "specs/phase-plans-v1.md"
        phases = {"ALPHA": "executing"}   # vs `committed` -> no done-vs-in-flight pair

    lines = render._manifest_disagreement_lines(_Snap())
    assert lines, "an unreadable row must not leave the prose surface silent"
    assert any("INCOMPLETE" in line for line in lines), lines
