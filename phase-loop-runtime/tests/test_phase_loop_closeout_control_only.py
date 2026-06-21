"""Regression tests for control-only / backfill phase closeout (#42).

A control/backfill phase legitimately owns no files: its plan declares
``(none)`` owned files (all lanes read-only), so ``parse_plan_ownership``
returns ``owned_patterns=()`` while staying ``valid=True``
(``PlanOwnership.is_control_only``). Such a verified phase used to be refused
at closeout with the misleading ``missing_phase_owned_dirty_paths`` /
``dirty_worktree_conflict`` blocker when it produced UNSAFE unowned dirt,
even though the *same* unsafe remainder on a plan that owns files is surfaced
as the typed ``closeout_scope_violation`` (partial-classify path).

This is v45 Phase 2B (CLOSEOUT), IF-0-CLOSEOUT-1. The fix:

- adds ``PlanOwnership.is_control_only`` (IF-0-FOUND-2), and
- routes a verified control-only phase's empty-owned dirt through the SAME
  v40 SAFE/UNSAFE/secrets policy the partial-classify path uses, so the
  misleading ``missing_phase_owned_dirty_paths`` no longer fires for a
  legitimately empty-owned verified phase.

v40 policy is preserved: SAFE dirt soft-commits, UNSAFE dirt requires an
operator break-glass reason, and ``secrets``-class paths are NEVER
break-glassable. A genuinely misconfigured plan (``missing_owned_files`` /
``malformed_owned_files``) still refuses.
"""

from __future__ import annotations

import subprocess

from phase_loop_runtime.discovery import parse_plan_ownership
from phase_loop_runtime.models import StateSnapshot, utc_now
from phase_loop_runtime.profiles import resolve_profile
from phase_loop_runtime.provenance import snapshot_provenance
from phase_loop_runtime.runner import _perform_phase_closeout
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan

MALFORMED_PLAN = """# BACKFILL

## Lanes

### SL-0 - Owned
- **Owned files**:
- **Interfaces provided**: none
- **Interfaces consumed**: none
"""


def _git(repo, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _control_only_plan(repo, roadmap):
    # owned_files=None renders "none (read-only lane)" -> valid=True, owned=()
    plan = write_phase_plan(repo, "BACKFILL", roadmap, owned_files=None)
    commit_fixture_paths(repo, "add control-only BACKFILL plan", plan)
    return plan


def _closeout_with_evidence(repo, roadmap, evidence, *, reason=None):
    for rel in evidence:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence\n", encoding="utf-8")
    snapshot = StateSnapshot(
        timestamp=utc_now(),
        repo=str(repo),
        roadmap=str(roadmap),
        phases={"BACKFILL": "awaiting_phase_closeout"},
        current_phase="BACKFILL",
        phase_owned_dirty=False,
        phase_owned_dirty_paths=(),
        dirty_paths=tuple(evidence),
        closeout_terminal_status="complete",
        **snapshot_provenance(roadmap),
    )
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    status, event = _perform_phase_closeout(
        repo,
        roadmap,
        "BACKFILL",
        snapshot,
        resolve_profile("execute"),
        action="execute",
        closeout_mode="commit",
        allow_unowned_reason=reason,
    )
    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return status, event, head_after != head_before


# ---------------------------------------------------------------------------
# PlanOwnership.is_control_only  (IF-0-FOUND-2)
# ---------------------------------------------------------------------------


def test_is_control_only_true_for_valid_empty_owned(tmp_path):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "BACKFILL", roadmap, owned_files=None)
    ownership = parse_plan_ownership(repo, roadmap, plan)
    assert ownership.valid is True
    assert ownership.owned_patterns == ()
    assert ownership.is_control_only is True


def test_is_control_only_false_for_invalid_empty_owned(tmp_path):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "BACKFILL", roadmap, body=MALFORMED_PLAN)
    ownership = parse_plan_ownership(repo, roadmap, plan)
    # malformed_owned_files -> invalid, so NOT control-only even though empty-owned.
    assert ownership.valid is False
    assert ownership.is_control_only is False


def test_is_control_only_false_when_plan_owns_files(tmp_path):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "BACKFILL", roadmap, owned_files=("src/foo.py",))
    ownership = parse_plan_ownership(repo, roadmap, plan)
    assert ownership.is_control_only is False


# ---------------------------------------------------------------------------
# Closeout behavior for verified control-only phases
# ---------------------------------------------------------------------------


def test_control_only_safe_evidence_closes_out(tmp_path):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo, roadmap, ["reports/natural-image/evidence.md"]
    )
    assert status == "complete", event.metadata.get("closeout")
    assert event.blocker is None
    assert committed is True


def test_control_only_unsafe_evidence_refuses_with_scope_violation_not_missing_paths(tmp_path):
    """The #42 core regression: control-only + UNSAFE evidence + no reason.

    Must surface the typed, break-glassable ``closeout_scope_violation`` —
    NOT the misleading ``missing_phase_owned_dirty_paths`` /
    ``dirty_worktree_conflict``.
    """
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo, roadmap, ["reports/retrieval-natural-image/run.json"]
    )
    closeout = event.metadata["closeout"]
    assert status == "blocked"
    assert committed is False
    assert event.blocker["blocker_class"] == "closeout_scope_violation"
    assert event.blocker["human_required"] is True
    assert closeout["closeout_refusal_reason"] == "unowned_dirty_remainder"
    assert closeout["closeout_refusal_reason"] != "missing_phase_owned_dirty_paths"
    assert "reports/retrieval-natural-image/run.json" in closeout["unowned_dirty_paths"]


def test_control_only_unsafe_evidence_breakglass_commits(tmp_path):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo,
        roadmap,
        ["reports/retrieval-natural-image/run.json"],
        reason="verified backfill evidence, audited",
    )
    assert status == "complete", event.metadata.get("closeout")
    assert event.blocker is None
    assert committed is True


def test_control_only_secret_evidence_never_breakglass(tmp_path):
    """secrets-class paths are NEVER break-glassable, even for a control-only phase."""
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo,
        roadmap,
        [".env"],
        reason="trust me",
    )
    assert status == "blocked"
    assert committed is False
    assert event.blocker["blocker_class"] == "closeout_scope_violation"
    assert ".env" in event.metadata["closeout"]["unowned_dirty_paths"]


def test_control_only_pem_secret_never_breakglass(tmp_path):
    """Belt-and-suspenders for the secrets guardrail across the secrets-class
    spectrum: a *.pem under secrets/ must block even with a break-glass reason."""
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo,
        roadmap,
        ["secrets/deploy.pem"],
        reason="audited, ship it",
    )
    assert status == "blocked"
    assert committed is False
    assert event.blocker["blocker_class"] == "closeout_scope_violation"
    assert "secrets/deploy.pem" in event.metadata["closeout"]["unowned_dirty_paths"]


def test_control_only_mixed_safe_and_unsafe_commits_safe_blocks_unsafe(tmp_path):
    """A control-only phase with both SAFE and UNSAFE dirt commits the SAFE
    subset and surfaces the UNSAFE remainder as closeout_scope_violation
    (the existing partial-classify path; guards it stays correct for
    control-only plans)."""
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo, roadmap, ["reports/x/notes.md", "reports/x/run.json"]
    )
    assert status == "blocked"
    # SAFE doc was committed; only the UNSAFE remainder blocks.
    assert committed is True
    assert event.blocker["blocker_class"] == "closeout_scope_violation"
    assert event.metadata["closeout"]["unowned_dirty_paths"] == ["reports/x/run.json"]


def test_control_only_control_dirt_closes_out(tmp_path):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo, roadmap, ["plans/manifest.json"]
    )
    assert status == "complete", event.metadata.get("closeout")
    assert event.blocker is None
    assert committed is True


def test_control_only_empty_override_reason_backstops(tmp_path):
    """A break-glass override with an empty reason (programmatic caller) must not
    force-commit unsafe dirt — it backstops to operator_override_missing_reason."""
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _control_only_plan(repo, roadmap)
    status, event, committed = _closeout_with_evidence(
        repo, roadmap, ["reports/x/run.json"], reason=""
    )
    assert status == "blocked"
    assert committed is False
    assert event.blocker["blocker_class"] == "operator_override_missing_reason"


def test_misconfigured_empty_owned_still_refuses(tmp_path):
    """Acceptance widening must not leak: a genuinely misconfigured plan
    (malformed owned-files) still refuses — as lane_ir_contract_bug."""
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "BACKFILL", roadmap, body=MALFORMED_PLAN)
    commit_fixture_paths(repo, "add malformed BACKFILL plan", plan)
    status, event, committed = _closeout_with_evidence(
        repo, roadmap, ["reports/x/run.json"]
    )
    assert status == "blocked"
    assert committed is False
    assert event.blocker["blocker_class"] == "contract_bug"
    assert event.metadata["closeout"]["closeout_refusal_reason"] == "lane_ir_contract_bug"
