"""v45 RECONCILE — git-reality reconciliation (IF-0-RECONCILE-1).

Scenario tests on real throwaway repos with merged closeout commits. The
load-bearing pair the prior attempt lacked:
  * a phase merged under vN, roadmap advanced to a byte-identical section under
    vN+1, work still present -> classifies ``complete``;
  * the SAME phase whose owned file was later reverted -> stays ``unplanned``
    (the B1 proof obligation: a completion commit proves "done once", not "still
    valid").

Active behavior is opt-in via ``PHASE_LOOP_RECONCILE_GIT_REALITY`` (safe cutover);
the default-off no-op is asserted explicitly.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.classifier import classify_phase
from phase_loop_runtime.discovery import reconcile_against_git_reality
from phase_loop_test_utils import make_repo, write_phase_plan

ENABLED = {"PHASE_LOOP_RECONCILE_GIT_REALITY": "true"}

PHASE_BLOCK = (
    "### Phase 1 — Widget (WIDGET)\n\n"
    "**Objective**\nBuild the widget.\n\n"
    "**Depends on**\n- (none)\n"
)
PHASE_BLOCK_EDITED = (
    "### Phase 1 — Widget (WIDGET)\n\n"
    "**Objective**\nBuild a COMPLETELY DIFFERENT widget.\n\n"
    "**Depends on**\n- (none)\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.DEVNULL)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _build_merged_then_advanced(
    tmp_path: Path,
    *,
    advanced_block: str,
    terminal_status: str = "complete",
) -> tuple[Path, Path]:
    """WIDGET planned+completed under v1, roadmap advanced to v2 (v1 removed)."""
    repo = make_repo(tmp_path)
    v1 = repo / "specs" / "phase-plans-v1.md"
    v1.write_text("# Roadmap\n\n" + PHASE_BLOCK)
    _commit(repo, "roadmap v1")

    write_phase_plan(repo, "WIDGET", v1, owned_files=("src/widget.py",))
    _commit(repo, "phase-loop plan: WIDGET")

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "widget.py").write_text("widget = True\n")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "phase-loop execute: WIDGET\n\n"
        "Plan: plans/phase-plan-v1-WIDGET.md\n"
        f"Terminal-Status: {terminal_status}\n"
        "Closeout-Commit: pending\n",
    )

    v2 = repo / "specs" / "phase-plans-v2.md"
    v2.write_text("# Roadmap v2\n\n" + advanced_block)
    v1.unlink()
    _commit(repo, "advance roadmap to v2")
    return repo, v2


def test_reconcile_promotes_renamed_phase_with_work_present(tmp_path):
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK)
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "complete"
        assert reconcile_against_git_reality(repo, v2, {"WIDGET": "unplanned"}) == {"WIDGET": "complete"}


def test_reconcile_does_not_promote_when_owned_file_reverted(tmp_path):
    # B1 PROOF OBLIGATION: identical section, but the owned file was reverted after
    # closeout -> the work no longer exists -> must NOT promote.
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK)
    (repo / "src" / "widget.py").unlink()
    _commit(repo, "revert widget work")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"
        assert reconcile_against_git_reality(repo, v2, {"WIDGET": "unplanned"}) == {"WIDGET": "unplanned"}


def test_reconcile_does_not_promote_when_owned_file_modified(tmp_path):
    # A later divergent edit to the owned file is also "not the same work".
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK)
    (repo / "src" / "widget.py").write_text("widget = 'something else entirely'\n")
    _commit(repo, "rewrite widget")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def test_reconcile_does_not_promote_edited_phase(tmp_path):
    # Criterion 4: a genuinely edited section is not a rename -> stays unplanned.
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK_EDITED)
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def test_reconcile_noop_without_completion_commit(tmp_path):
    repo = make_repo(tmp_path)
    v1 = repo / "specs" / "phase-plans-v1.md"
    v1.write_text("# Roadmap\n\n" + PHASE_BLOCK)
    _commit(repo, "roadmap v1")
    write_phase_plan(repo, "WIDGET", v1, owned_files=("src/widget.py",))
    _commit(repo, "phase-loop plan: WIDGET")  # planned only, no completion commit
    v2 = repo / "specs" / "phase-plans-v2.md"
    v2.write_text("# Roadmap v2\n\n" + PHASE_BLOCK)
    v1.unlink()
    _commit(repo, "advance roadmap to v2")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def test_terminal_status_is_parsed_trailer_not_substring(tmp_path):
    # B2: a body that merely MENTIONS the phrase in prose (not as a trailer) and
    # carries a non-complete trailer must not promote.
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK, terminal_status="blocked")
    # Even though the prose below contains the phrase, the parsed trailer is 'blocked'.
    (repo / "NOTES.md").write_text("note: Terminal-Status: complete appears here as prose\n")
    _commit(repo, "add prose mentioning Terminal-Status: complete")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def test_reconcile_never_demotes(tmp_path):
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK_EDITED)
    classifications = {"WIDGET": "complete", "OTHER": "blocked"}
    with patch.dict("os.environ", ENABLED):
        assert reconcile_against_git_reality(repo, v2, classifications) == classifications


def _completion_commit(repo: Path, *, plan_rel: str, terminal_status: str, body_prefix: str = "") -> None:
    """Commit staged work with a closeout-style trailer block. ``body_prefix`` is
    free prose placed ABOVE the trailer paragraph (used to prove prose can't forge
    a trailer)."""
    message = "phase-loop execute: WIDGET\n\n"
    if body_prefix:
        message += body_prefix + "\n\n"
    message += f"Plan: {plan_rel}\nTerminal-Status: {terminal_status}\nCloseout-Commit: pending\n"
    _git(repo, "commit", "-q", "-m", message)


def test_does_not_promote_invalid_unparseable_plan(tmp_path):
    # BLOCKER 1 (review): a completion commit whose plan no longer parses (empty
    # owned-patterns + valid=False) must NOT promote — _owned_work_persists_to_head
    # returns is_control_only (False for invalid), not a blind True.
    repo = make_repo(tmp_path)
    v1 = repo / "specs" / "phase-plans-v1.md"
    v1.write_text("# Roadmap\n\n" + PHASE_BLOCK)
    _commit(repo, "roadmap v1")
    roadmap_hash = hashlib.sha256(v1.read_bytes()).hexdigest()
    plan = repo / "plans" / "phase-plan-v1-WIDGET.md"
    # Valid frontmatter (so section-sha recompute works) but a body with NO lane
    # sections -> parse_plan_ownership -> owned=(), valid=False.
    plan.write_text(
        "---\nphase_loop_plan_version: 1\nphase: WIDGET\n"
        "roadmap: specs/phase-plans-v1.md\n"
        f"roadmap_sha256: {roadmap_hash}\n---\n# WIDGET\n\nNo lane sections at all.\n"
    )
    _commit(repo, "plan: WIDGET (unparseable ownership)")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "widget.py").write_text("widget = True\n")
    _git(repo, "add", "-A")
    _completion_commit(repo, plan_rel="plans/phase-plan-v1-WIDGET.md", terminal_status="complete")
    v2 = repo / "specs" / "phase-plans-v2.md"
    v2.write_text("# Roadmap v2\n\n" + PHASE_BLOCK)
    v1.unlink()
    _commit(repo, "advance roadmap to v2")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def test_does_not_promote_prose_terminal_status_in_commit_body(tmp_path):
    # BLOCKER 2 (review): the completion commit's REAL trailer is `blocked`, but its
    # body PROSE mentions `Terminal-Status: complete`. A body-substring scan would
    # forge a completion; git's trailer parser must read `blocked` -> no promotion.
    repo = make_repo(tmp_path)
    v1 = repo / "specs" / "phase-plans-v1.md"
    v1.write_text("# Roadmap\n\n" + PHASE_BLOCK)
    _commit(repo, "roadmap v1")
    write_phase_plan(repo, "WIDGET", v1, owned_files=("src/widget.py",))
    _commit(repo, "plan: WIDGET")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "widget.py").write_text("widget = True\n")
    _git(repo, "add", "-A")
    _completion_commit(
        repo,
        plan_rel="plans/phase-plan-v1-WIDGET.md",
        terminal_status="blocked",
        body_prefix="An earlier run reported Terminal-Status: complete but we reverted it.",
    )
    v2 = repo / "specs" / "phase-plans-v2.md"
    v2.write_text("# Roadmap v2\n\n" + PHASE_BLOCK)
    v1.unlink()
    _commit(repo, "advance roadmap to v2")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def _build_glob_owned(tmp_path: Path, slug: str, *, owned: tuple[str, ...]) -> tuple[Path, Path]:
    repo = make_repo(tmp_path / slug)
    v1 = repo / "specs" / "phase-plans-v1.md"
    v1.write_text("# Roadmap\n\n" + PHASE_BLOCK)
    _commit(repo, "roadmap v1")
    write_phase_plan(repo, "WIDGET", v1, owned_files=owned)
    _commit(repo, "plan: WIDGET")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "widget.py").write_text("widget = True\n")
    _git(repo, "add", "-A")
    _completion_commit(repo, plan_rel="plans/phase-plan-v1-WIDGET.md", terminal_status="complete")
    v2 = repo / "specs" / "phase-plans-v2.md"
    v2.write_text("# Roadmap v2\n\n" + PHASE_BLOCK)
    v1.unlink()
    _commit(repo, "advance roadmap to v2")
    return repo, v2


def test_glob_owned_work_present_promotes(tmp_path):
    # Positive control: a glob owned pattern the runtime's matcher resolves, with
    # work present, still promotes (the persistence check isn't over-conservative).
    repo, v2 = _build_glob_owned(tmp_path, "present", owned=("src/**",))
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "complete"


def test_deep_glob_owned_file_deletion_blocks_promotion(tmp_path):
    # MAJOR 3 (review): owned `src/**/*.py` with the file DIRECTLY under src/. git's
    # glob pathspec misses this deletion (`git diff --quiet -- 'src/**/*.py'` -> rc 0),
    # so the old code falsely promoted. Resolving owned files via the codebase
    # matcher over the commit tree + diffing exact paths blocks it.
    repo, v2 = _build_glob_owned(tmp_path, "deleted", owned=("src/**/*.py",))
    (repo / "src" / "widget.py").unlink()
    _commit(repo, "revert deep-glob work")
    with patch.dict("os.environ", ENABLED):
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"


def test_flag_off_is_noop_even_with_completion_commit(tmp_path):
    # SAFE CUTOVER: default-off -> identity no-op = today's behavior, even when a
    # promotable completion commit exists.
    repo, v2 = _build_merged_then_advanced(tmp_path, advanced_block=PHASE_BLOCK)
    with patch.dict("os.environ", {"PHASE_LOOP_RECONCILE_GIT_REALITY": "false"}):
        assert reconcile_against_git_reality(repo, v2, {"WIDGET": "unplanned"}) == {"WIDGET": "unplanned"}
        assert classify_phase(repo, v2, "WIDGET") == "unplanned"
    # And with the env var entirely absent (true default).
    import os

    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("PHASE_LOOP_RECONCILE_GIT_REALITY", None)
        assert reconcile_against_git_reality(repo, v2, {"WIDGET": "unplanned"}) == {"WIDGET": "unplanned"}
