"""RUNCORE lane (d) — an explicit ``--phase`` is honored on the concurrent
scheduler (coordinator-waves) path.

The serial selector ``_select_ready_phase(repo, roadmap, classifications, phase)``
already honors an explicit phase; the concurrent coordinator-waves selector
``_select_parallel_dispatch_phase`` did not accept a ``phase`` argument at all, so it
could only pick by wave order and a fully-blocked earlier wave halted the loop.

Reachability note (CR): today ``coordinator_waves`` is populated only when ``phase``
is ``None`` (its derivation is gated on ``phase is None``), so through ``run_loop``
this selector is never called with an explicit phase — the explicit-phase case is
served by ``_select_ready_phase``. Threading ``phase`` here is therefore a
**defensive consistency** guarantee (the helper honors an explicit phase, bounded to
the wave structure, if that invariant ever changes), not a fix for a currently
reachable production defect. These tests pin the helper's contract directly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.runner import _select_parallel_dispatch_phase
from phase_loop_runtime.launcher import LaunchResult
from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, make_repo, write_phase_plan
from test_phase_worktree_executor import require_sched_red

WAVES = (("SEAL",), ("ROOM", "AVAIL"))
CLASSIFICATIONS = {"SEAL": "blocked", "ROOM": "planned", "AVAIL": "unplanned"}


def test_explicit_phase_is_honored_over_wave_order():
    # Without the explicit phase, the first wave is fully blocked so the selector
    # halts (returns None) — the pre-fix behavior that stranded a ready ROOM.
    assert _select_parallel_dispatch_phase(WAVES, CLASSIFICATIONS) is None
    # With the explicit phase, the ready independent ROOM is dispatched.
    assert _select_parallel_dispatch_phase(WAVES, CLASSIFICATIONS, "ROOM") == "ROOM"


def test_explicit_phase_is_uppercased():
    assert _select_parallel_dispatch_phase(WAVES, CLASSIFICATIONS, "room") == "ROOM"


def test_explicit_phase_not_in_any_wave_selects_nothing():
    assert _select_parallel_dispatch_phase(WAVES, CLASSIFICATIONS, "NOPE") is None


def test_no_explicit_phase_preserves_wave_selection():
    # Backcompat: the default (no explicit phase) selection is unchanged.
    waves = (("ROOM", "AVAIL"),)
    classifications = {"ROOM": "planned", "AVAIL": "unplanned"}
    assert _select_parallel_dispatch_phase(waves, classifications) == "ROOM"
    assert _select_parallel_dispatch_phase(waves, classifications, None) == "ROOM"


@require_sched_red
def test_no_diff_result_requires_an_explicit_artifact_verification_skip():
    from phase_loop_runtime import runner

    # Drive the production run/reduction path.  The verifier boundary is only
    # observed, not replaced by a proposed no-diff helper: a true no-diff result
    # must never enter artifact-dependent verification.
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(Path(td))
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text(
            "# Roadmap\n\n### Phase 1 - Room (ROOM)\n**Depends on**\n- (none)\n",
            encoding="utf-8",
        )
        plan = write_phase_plan(repo, "ROOM", roadmap, owned_files=("src/room.py",))
        commit_fixture_paths(repo, "add no-diff plan", roadmap, plan)
        verification_calls = []

        def no_diff_launch(spec, **_kwargs):
            result = LaunchResult(
                command=spec.command,
                returncode=0,
                output=build_fake_automation_output(
                    status="complete",
                    verification_status="passed",
                    artifact=str(plan),
                    artifact_state="tracked",
                ),
                executor=spec.executor,
            )
            object.__setattr__(result, "changed_paths", ())
            return result

        def observe_verification(*args, **kwargs):
            verification_calls.append(kwargs.get("phase_alias"))
            return {"ok": True, "status": "observed"}

        with (
            patch("phase_loop_runtime.runner.launch_with_spec", side_effect=no_diff_launch),
            patch("phase_loop_runtime.runner._run_execute_verification", side_effect=observe_verification),
            patch("phase_loop_runtime.injection._resolve_pack_skill_dirs", return_value={}),
        ):
            snapshot, _ = runner.run_loop(repo, roadmap, phase="ROOM")

        assert snapshot.phases["ROOM"] == "complete"
        assert verification_calls == []
