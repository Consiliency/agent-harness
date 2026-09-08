"""RED-first falsifiers for the sealed-inventory worktree lifecycle (ah#789, Workstream B).

Consiliency/agent-harness#789 step 2: a sealed zero-history bootstrap inventory
names a worktree by PATH, and once that worktree is pruned every resume /
revalidation reader (``_revalidate_bootstrap_sources`` and the latch opening in
``bootstrap_zero_history_authority``) dies inside ``_git_out`` with the
incident's ``No such file`` text -- even though ``CanonicalRepositoryIdentity.v1``
never hashed the worktree path, only the Git COMMON dir.

Plan: ``plans/detailed-789-fabpub-pre-admission-compat-20260906.md`` (Workstream
B).  Production adds ``live._inventory_row_repository(row)``: the row's worktree
when it is still a Git working tree, else the recorded common dir
(``Path(row["namespace_root"]).parent``) with one structured warning, else a
fail-closed ``LegacyCutoverConflict`` naming the pruned worktree and the missing
common dir.

TDD contract (the shape of ``tests/_fabpub_tdd_guard.py``, which this module
does not edit):

* activation is the exact env ``PHASE_LOOP_TDD_EXPECT_789=1`` OR the presence of
  the production helper ``live._inventory_row_repository``;
* only the production-dependent nodeids ``skipif`` while inactive, all with the
  one reason below; no module-level skip, no ``xfail``;
* the guard-control (path re-used by a DIFFERENT repository -> "repository
  identity changed after seal") never skips: it holds at base and must keep
  holding after B, proving the helper did not loosen identity;
* every activated falsifier fails with an ``AssertionError`` carrying a unique
  ``789-RED-ANCHOR::`` marker, never a bare ``LegacyCutoverConflict`` traceback.

Stated limit (plan finding F2, carried not claimed): a different repository
re-created at the SAME common-dir path with the same object format has the same
identity at base and after B; no test here promises that refusal.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from phase_loop_runtime.convergence.broker import live
from test_fabpub_zero_history_bootstrap import _git_repo, _probe

ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_789"
PRODUCTION_HELPER = "_inventory_row_repository"
SKIP_REASON = (
    "ah#789 Workstream B production helper live._inventory_row_repository is absent "
    "(tests_only lane): set PHASE_LOOP_TDD_EXPECT_789=1 to run this falsifier "
    "against production"
)


def _activated() -> bool:
    return os.environ.get(ACTIVATION_ENV) == "1" or hasattr(live, PRODUCTION_HELPER)


_production_dependent = pytest.mark.skipif(not _activated(), reason=SKIP_REASON)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, timeout=60
    )
    return completed.stdout.strip()


def _linked_worktree(main: Path, path: Path, branch: str) -> Path:
    """A REAL linked worktree of ``main`` (``git worktree add``), resolved."""
    _git("-C", str(main), "worktree", "add", "-q", "-b", branch, str(path))
    return path.resolve()


def _remove_linked_worktree(main: Path, linked: Path) -> None:
    _git("-C", str(main), "worktree", "remove", str(linked))
    _git("-C", str(main), "worktree", "prune")
    assert not linked.exists()


def _sealed_row(inventory: dict) -> dict:
    (row,) = inventory["worktrees"]
    return row


def _journal_bytes(tmp_path: Path) -> bytes:
    return (tmp_path / "authority" / "bootstrap-test.bootstrap-journal.jsonl").read_bytes()


def _fallback_signals(caught, caplog, *result_dicts) -> list[str]:
    """Every warning-class message the resume emitted, over the channels the plan
    allows ("existing report/journal mechanism, not print"): the ``warnings``
    module, ``logging`` at WARNING+, and a ``warnings`` list on a returned report."""
    messages = [str(item.message) for item in caught]
    messages += [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    for result in result_dicts:
        if isinstance(result, dict):
            messages += [str(item) for item in result.get("warnings", ())]
    return messages


# ---------------------------------------------------------------------------
# positive: pruned linked worktree, resume succeeds through the common dir
# ---------------------------------------------------------------------------


@_production_dependent
def test_sealed_linked_worktree_removed_then_resume_succeeds_with_warning(
    tmp_path: Path, caplog
) -> None:
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    common = Path(row["namespace_root"]).parent
    assert row["worktree"] == str(linked)
    assert common == live.git_common_dir(main)
    # Identity was never path-derived: the primary checkout and the linked
    # worktree agree at base (live.py CanonicalRepositoryIdentity.v1).
    assert live.repository_snapshot(main).identity == row["canonical_repository_identity"]

    first = live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert first["state"] == "ACTIVE"
    assert first["repositories"] == [row["canonical_repository_identity"]]

    _remove_linked_worktree(main, linked)
    journal_before = _journal_bytes(tmp_path)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        caplog.set_level(logging.WARNING)
        try:
            assert live.global_active_authority_exists(authority_root=tmp_path / "authority")
            second = live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )
        except live.LegacyCutoverConflict as exc:
            raise AssertionError(
                "789-RED-ANCHOR::pruned-worktree-resume — resume after `git worktree "
                f"remove {linked}` must succeed through the sealed common dir {common}; "
                f"got the incident failure instead: {exc}"
            ) from exc

    # Compare the stable activation fields, not the whole report: the plan lets
    # production carry the fallback warning on the returned report, and a
    # ``warnings`` key there is diagnostics, not a different ACTIVE result.
    assert second["state"] == first["state"] == "ACTIVE"
    assert second["repositories"] == first["repositories"]
    assert second["repositories"] == [row["canonical_repository_identity"]]
    receipt = live.load_partition_receipt(live.repository_snapshot(main).store_root)
    assert receipt is not None
    assert receipt.canonical_repository_identity == row["canonical_repository_identity"]
    assert live.WriterGenerationLatch.open(main).read().generation_state == "ACTIVE"
    # The journal is the other carrier the plan allows.  A resume may append a
    # warning record but must not move the bootstrap state; the byte-exact
    # "nothing written" pin belongs to the refusal test below.
    journal_after = _journal_bytes(tmp_path)
    assert journal_after.startswith(journal_before), "a resume never rewrites journal history"
    appended_journal = journal_after[len(journal_before):].decode("utf-8", "replace")

    signals = _fallback_signals(caught, caplog, second)
    signals += [line for line in appended_journal.splitlines() if line.strip()]
    fallback = [m for m in signals if str(linked) in m and str(common) in m]
    assert fallback, (
        "789-RED-ANCHOR::pruned-worktree-warning — falling back from the pruned "
        f"worktree {linked} to the common dir {common} must emit one structured warning "
        f"naming both; warning-class messages seen: {signals!r}"
    )


# ---------------------------------------------------------------------------
# negative 1: worktree AND common dir gone -> fail closed, no journal write
# ---------------------------------------------------------------------------


@_production_dependent
def test_sealed_worktree_and_common_dir_gone_refuses_without_journal_transition(
    tmp_path: Path, monkeypatch
) -> None:
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    common = Path(row["namespace_root"]).parent
    authority = tmp_path / "authority"
    journal = authority / "bootstrap-test.bootstrap-journal.jsonl"

    # Interrupt the first apply right after DRAINING is journaled so the resume
    # still has a transition left to (wrongly) write.
    with monkeypatch.context() as patcher:
        patcher.setattr(
            live.WriterGenerationLatch,
            "open",
            classmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash"))
            ),
        )
        with pytest.raises(RuntimeError, match="crash"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert live._bootstrap_journal_states(journal, "bootstrap-test") == ("DRAINING",)
    assert (authority / "bootstrap-test.bootstrap-inventory.json").exists()
    assert not (authority / "ACTIVE_BOOTSTRAP").exists()

    _remove_linked_worktree(main, linked)
    shutil.rmtree(main)
    assert not common.exists()
    journal_before = journal.read_bytes()

    with pytest.raises(live.LegacyCutoverConflict) as raised:
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    message = str(raised.value)
    actionable = (
        "names pruned worktree" in message
        and "is gone" in message
        and "restore the repository or rotate the authority" in message
        and str(linked) in message
        and str(common) in message
        and row["canonical_repository_identity"] in message
    )
    assert actionable, (
        "789-RED-ANCHOR::common-dir-gone-actionable-refusal — with worktree "
        f"{linked} pruned and common dir {common} gone the resume must refuse with the "
        f"actionable message naming both and identity "
        f"{row['canonical_repository_identity']}; got: {message}"
    )

    assert journal.read_bytes() == journal_before, "a refused resume writes no journal state"
    assert live._bootstrap_journal_states(journal, "bootstrap-test") == ("DRAINING",)
    assert not (authority / "ACTIVE_BOOTSTRAP").exists()


# ---------------------------------------------------------------------------
# negative 2 (guard-control, never skips): identity equality still bites
# ---------------------------------------------------------------------------


def test_sealed_worktree_path_reused_by_different_repository_refuses_identity_change(
    tmp_path: Path,
) -> None:
    """The sealed path now belongs to a DIFFERENT repository (different common
    dir): the existing "repository identity changed after seal" refusal fires at
    base and must keep firing after B.  Not F2: the common dir differs."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    authority = tmp_path / "authority"
    first = live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert first["state"] == "ACTIVE"
    journal_before = _journal_bytes(tmp_path)

    _remove_linked_worktree(main, linked)
    other = _git_repo(tmp_path / "other")
    reused = _linked_worktree(other, tmp_path / "linked", "reused")
    assert reused == linked
    assert live.git_common_dir(reused) != Path(row["namespace_root"]).parent
    assert live.repository_snapshot(reused).identity != row["canonical_repository_identity"]

    with pytest.raises(live.LegacyCutoverConflict, match="repository identity changed after seal"):
        live.global_active_authority_exists(authority_root=authority)
    with pytest.raises(live.LegacyCutoverConflict, match="repository identity changed after seal"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert _journal_bytes(tmp_path) == journal_before
    assert live.load_partition_receipt(live.repository_snapshot(other).store_root) is None


# ---------------------------------------------------------------------------
# negative 2 (fallback form): the common-dir fallback resolves to a DIFFERENT
# repository -> the same identity refusal, not a silent adoption
# ---------------------------------------------------------------------------


@_production_dependent
def test_fallback_common_dir_of_different_repository_refuses_identity_change(
    tmp_path: Path,
) -> None:
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"
    _remove_linked_worktree(main, linked)

    other = _git_repo(tmp_path / "other")
    other_common = live.git_common_dir(other)
    assert other_common != Path(row["namespace_root"]).parent
    # Same sealed identity, worktree pruned, namespace_root re-pointed at another
    # repository's common dir: the helper's fallback must feed the identity
    # equality in _revalidate_bootstrap_sources, which must then refuse.
    tampered = copy.deepcopy(inventory)
    _sealed_row(tampered)["namespace_root"] = str(live.repository_namespace_root(other))

    try:
        live._revalidate_bootstrap_sources(tampered)
    except live.LegacyCutoverConflict as exc:
        message = str(exc)
        assert "repository identity changed after seal" in message, (
            "789-RED-ANCHOR::fallback-different-repository-identity — with worktree "
            f"{linked} pruned and namespace_root re-pointed at {other_common}, "
            "revalidation must reach the identity equality and refuse with "
            f"'repository identity changed after seal'; got: {message}"
        )
    else:
        raise AssertionError(
            "789-RED-ANCHOR::fallback-different-repository-adopted — revalidation "
            f"accepted a fallback to {other_common} whose identity differs from the "
            f"sealed {row['canonical_repository_identity']}"
        )
    assert live.load_partition_receipt(live.repository_snapshot(other).store_root) is None


# ---------------------------------------------------------------------------
# negative 3 (added with production, ah#789 Workstream B): the fallback stands
# in ONLY for the recorded common dir itself -- a directory that merely sits
# inside the same repository is refused actionably, never adopted
# ---------------------------------------------------------------------------


@_production_dependent
def test_fallback_path_that_is_not_the_common_dir_refuses_actionably(
    tmp_path: Path,
) -> None:
    """The plan's helper self-check (``rev-parse --git-common-dir`` of the
    fallback must resolve to the fallback itself).  Without it a
    ``namespace_root`` re-pointed at any directory inside the SAME repository
    would be adopted silently: the identity equality still holds there, so only
    the self-check separates "the recorded common dir" from "some path"."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"
    _remove_linked_worktree(main, linked)

    inside = main / "not-the-common-dir"
    inside.mkdir()
    assert live.git_common_dir(inside) == Path(row["namespace_root"]).parent
    tampered = copy.deepcopy(inventory)
    _sealed_row(tampered)["namespace_root"] = str(inside / live.REPOSITORY_NAMESPACE_DIR)

    try:
        live._revalidate_bootstrap_sources(tampered)
    except live.LegacyCutoverConflict as exc:
        message = str(exc)
        actionable = (
            "names pruned worktree" in message
            and "restore the repository or rotate the authority" in message
            and str(linked) in message
            and str(inside) in message
        )
        assert actionable, (
            "789-RED-ANCHOR::fallback-non-common-dir-not-actionable — with worktree "
            f"{linked} pruned and namespace_root re-pointed inside the repository at "
            f"{inside}, revalidation must refuse with the actionable message naming "
            f"both; got: {message}"
        )
    else:
        raise AssertionError(
            "789-RED-ANCHOR::fallback-non-common-dir-adopted — revalidation adopted "
            f"{inside}, which is inside the sealed repository but is not its common "
            f"dir {Path(row['namespace_root']).parent}"
        )


# ---------------------------------------------------------------------------
# binding by repository, not path (ah#804 round 1, fable F1/F2/F3 + codex
# DRAINING coverage): ``RepositorySnapshot.worktree`` is not identity-bearing,
# so no reader may compare a sealed ``worktree`` string against it once the
# fallback has taken the snapshot from the common dir.
# ---------------------------------------------------------------------------


def _crash_at_proof_phase(monkeypatch, phase: str, marker: str):
    real = live._prove_zero_source

    def boom(snapshot, roots, current_phase):
        if current_phase == phase:
            raise RuntimeError(marker)
        return real(snapshot, roots, current_phase)

    monkeypatch.setattr(live, "_prove_zero_source", boom)


def _onboarding_inventory_path(row: dict) -> Path:
    return (
        Path(row["namespace_root"]) / "zero-legacy-onboarding" / "bootstrap-test.inventory.json"
    )


@_production_dependent
def test_interrupted_onboarding_resumes_after_worktree_prune(
    tmp_path: Path, monkeypatch
) -> None:
    """fable F2: the onboarding inventory (``bootstrap_in_progress``) was sealed
    against the linked worktree; after the prune the resume classifies the
    repository from its common dir and must still bind by repository."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)

    with monkeypatch.context() as patcher:
        _crash_at_proof_phase(patcher, "before_receipt_write", "crash-after-onboarding-seal")
        with pytest.raises(RuntimeError, match="crash-after-onboarding-seal"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert _onboarding_inventory_path(row).exists(), "did not reach bootstrap_in_progress"
    assert live.load_partition_receipt(live.repository_snapshot(main).store_root) is None

    _remove_linked_worktree(main, linked)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", live.SealedWorktreeFallbackWarning)
        try:
            result = live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )
        except live.LegacyCutoverConflict as exc:
            raise AssertionError(
                "789-RED-ANCHOR::interrupted-onboarding-prune-resume — an onboarding "
                f"interrupted after its inventory seal must resume after `git worktree "
                f"remove {linked}`; the sealed partition names the worktree but the "
                f"identity is the common dir; got: {exc}"
            ) from exc
    assert result["state"] == "ACTIVE"
    assert result["repositories"] == [row["canonical_repository_identity"]]
    receipt = live.load_partition_receipt(live.repository_snapshot(main).store_root)
    assert receipt is not None and receipt.zero_source
    assert live.WriterGenerationLatch.open(main).read().generation_state == "ACTIVE"


@_production_dependent
def test_restore_after_fallback_resume_succeeds(tmp_path: Path, monkeypatch) -> None:
    """fable F1: a resume that onboarded through the common-dir fallback must
    seal the ROW's recorded worktree, not the ``.git`` dir it happened to
    snapshot, so restoring the worktree at the recorded path resumes cleanly."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)

    # First apply crashes BEFORE onboarding: the authority is sealed, nothing
    # under the repository namespace yet beyond the latch.
    with monkeypatch.context() as patcher:
        patcher.setattr(
            live,
            "onboard_zero_legacy_repository",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash-1")),
        )
        with pytest.raises(RuntimeError, match="crash-1"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert not _onboarding_inventory_path(row).exists()

    _remove_linked_worktree(main, linked)
    # Resume through the fallback, crashing after the onboarding inventory seal.
    with monkeypatch.context() as patcher, warnings.catch_warnings():
        warnings.simplefilter("ignore", live.SealedWorktreeFallbackWarning)
        _crash_at_proof_phase(patcher, "before_receipt_write", "crash-2")
        with pytest.raises(RuntimeError, match="crash-2"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    sealed = json.loads(_onboarding_inventory_path(row).read_text(encoding="utf-8"))
    (partition,) = sealed["partitions"].values()
    assert partition["worktree"] == row["worktree"], (
        "789-RED-ANCHOR::fallback-onboarding-seals-common-dir — the onboarding "
        f"partition sealed worktree {partition['worktree']!r} instead of the sealed "
        f"row's recorded worktree {row['worktree']!r}"
    )

    restored = _linked_worktree(main, Path(row["worktree"]), "restored")
    assert restored == linked and live.is_git_repository(restored)
    try:
        result = live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    except live.LegacyCutoverConflict as exc:
        raise AssertionError(
            "789-RED-ANCHOR::restore-after-fallback-refused — after the worktree was "
            f"restored at its recorded path {linked} the resume must succeed; got: {exc}"
        ) from exc
    assert result["state"] == "ACTIVE"
    assert result["repositories"] == [row["canonical_repository_identity"]]
    assert live.WriterGenerationLatch.open(restored).read().generation_state == "ACTIVE"


@_production_dependent
def test_fresh_apply_after_prune_refuses_actionably(tmp_path: Path) -> None:
    """fable F3: nothing durable exists before the first apply's re-probe, so a
    pruned row must refuse with a message that names the remedy (re-probe),
    never the misleading "inventory changed between probe and apply"."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    authority = tmp_path / "authority"
    _remove_linked_worktree(main, linked)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", live.SealedWorktreeFallbackWarning)
        with pytest.raises(live.LegacyCutoverConflict) as raised:
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    message = str(raised.value)
    actionable = (
        "before its first apply" in message
        and "re-run the zero-history probe" in message
        and str(linked) in message
        and row["canonical_repository_identity"] in message
    )
    assert actionable, (
        "789-RED-ANCHOR::fresh-apply-after-prune-not-actionable — a first apply whose "
        f"sealed worktree {linked} was pruned must refuse naming the pruned path, the "
        f"identity and the re-probe remedy; got: {message}"
    )
    assert not (authority / "bootstrap-test.bootstrap-inventory.json").exists()
    assert not (authority / "bootstrap-test.bootstrap-journal.jsonl").exists()
    assert not (authority / "ACTIVE_BOOTSTRAP").exists()


@_production_dependent
def test_draining_resume_after_prune_awaits_quiescence(
    tmp_path: Path, monkeypatch
) -> None:
    """codex r1 residual: a resume whose latch is still DRAINING must run
    ``await_quiescent(worktree=<common dir>)`` through the fallback path."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    authority = tmp_path / "authority"
    journal = authority / "bootstrap-test.bootstrap-journal.jsonl"

    real_record = live._record_bootstrap_state

    def crash_before_seal(path: Path, cutover_id: str, state: str) -> None:
        if state == "INVENTORY_SEALED":
            raise RuntimeError("crash-before-inventory-sealed")
        real_record(path, cutover_id, state)

    with monkeypatch.context() as patcher:
        patcher.setattr(live, "_record_bootstrap_state", crash_before_seal)
        with pytest.raises(RuntimeError, match="crash-before-inventory-sealed"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert live._bootstrap_journal_states(journal, "bootstrap-test") == ("DRAINING",)
    assert live.WriterGenerationLatch.open(main).read().generation_state == "DRAINING"

    _remove_linked_worktree(main, linked)
    common = Path(row["namespace_root"]).parent
    awaited: list[Path] = []
    real_await = live.WriterGenerationLatch.await_quiescent

    def spy(self, *, worktree, timeout=60.0):
        awaited.append(Path(worktree))
        return real_await(self, worktree=worktree, timeout=timeout)

    with monkeypatch.context() as patcher, warnings.catch_warnings():
        warnings.simplefilter("ignore", live.SealedWorktreeFallbackWarning)
        patcher.setattr(live.WriterGenerationLatch, "await_quiescent", spy)
        result = live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert result["state"] == "ACTIVE"
    assert common in awaited, (
        "789-RED-ANCHOR::draining-resume-quiescence — a DRAINING resume after the "
        f"prune must await quiescence through the common dir {common}; awaited: {awaited!r}"
    )
    assert live.WriterGenerationLatch.open(main).read().generation_state == "ACTIVE"
    assert live._bootstrap_journal_states(journal, "bootstrap-test") == live.ZERO_HISTORY_STATES


@_production_dependent
def test_recorded_worktree_replaced_by_plain_dir_refuses(
    tmp_path: Path, monkeypatch
) -> None:
    """The foreign-directory branch of ``_recorded_worktree_binds``: the sealed
    partition's ``worktree`` path still exists after the prune but is a plain
    directory, not a working tree of the recorded repository.  The identity
    still matches through the common-dir fallback, so only the worktree clause
    separates "pruned" from "reused by something else"; a helper that always
    binds would resume onto the foreign path silently."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)

    with monkeypatch.context() as patcher:
        _crash_at_proof_phase(patcher, "before_receipt_write", "crash-after-onboarding-seal")
        with pytest.raises(RuntimeError, match="crash-after-onboarding-seal"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert _onboarding_inventory_path(row).exists(), "did not reach bootstrap_in_progress"

    _remove_linked_worktree(main, linked)
    linked.mkdir()
    assert not live.is_git_repository(linked)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", live.SealedWorktreeFallbackWarning)
        try:
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
        except live.LegacyCutoverConflict as exc:
            message = str(exc)
        else:
            raise AssertionError(
                "789-RED-ANCHOR::recorded-worktree-reused-by-plain-dir — with the sealed "
                f"worktree {linked} pruned and replaced by a plain directory, the resume "
                "must refuse instead of binding the onboarding inventory to a foreign path"
            )
    assert "is not bound to" in message and str(linked) in message, message
    assert live.load_partition_receipt(live.repository_snapshot(main).store_root) is None


# ---------------------------------------------------------------------------
# round 3 (ah#804, fable r2 #1/#2): a recorded worktree that IS its own Git
# common dir -- a bare repository or a ``<repo>/.git`` path -- is not pruned.
# ``is_git_repository`` is False for both (``--is-inside-work-tree`` answers
# "false" from inside a Git dir), so the first-apply guard must also accept a
# path that ``rev-parse --git-common-dir`` resolves to itself, and the resume
# fallback must not warn when the fallback IS the recorded path.
# ---------------------------------------------------------------------------


def _bare_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True, timeout=60)
    return path.resolve()


NON_WORKTREE_KINDS = ["bare", "dotgit", "gitobjects"]


def _non_worktree_repo_path(tmp_path: Path, kind: str) -> Path:
    """A path ``repository_snapshot`` seals but ``is_git_repository`` rejects:
    a bare repository, ``<repo>/.git`` (both their own common dir), or
    ``<repo>/.git/objects`` (codex r3: discovers the repository without being
    its common dir)."""
    if kind == "bare":
        return _bare_repo(tmp_path / "bare.git")
    main = _git_repo(tmp_path / "main")
    if kind == "gitobjects":
        return (main / ".git" / "objects").resolve()
    return (main / ".git").resolve()


def _assert_non_worktree_fixture(recorded: Path, kind: str) -> None:
    assert not live.is_git_repository(recorded), "fixture is a working tree"
    if kind == "gitobjects":
        # The discovery class, not the own-common-dir class: the fixture only
        # exercises the guard if the stricter helper still rejects it.
        assert not live._path_is_own_common_dir(recorded), "fixture is its own common dir"


@_production_dependent
@pytest.mark.parametrize("kind", NON_WORKTREE_KINDS)
def test_first_apply_accepts_row_recording_non_worktree_repo_path(
    tmp_path: Path, kind: str
) -> None:
    """A probe sealed against a bare repository, a ``<repo>/.git`` path, or a
    ``<repo>/.git/objects`` path applied at base; every one of them is a path
    ``repository_snapshot`` sealed, so the first-apply pruned-row guard must
    not refuse it (codex r3: refusing ``.git/objects`` prescribed a re-probe
    that re-sealed the same row), and no ``SealedWorktreeFallbackWarning`` may
    fire (nothing was pruned)."""
    recorded = _non_worktree_repo_path(tmp_path, kind)
    _assert_non_worktree_fixture(recorded, kind)
    inventory = _probe(tmp_path, recorded)
    row = _sealed_row(inventory)
    assert Path(row["worktree"]).resolve() == recorded

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )
        except live.LegacyCutoverConflict as exc:
            raise AssertionError(
                "789-RED-ANCHOR::first-apply-non-worktree-repo-path-refused — a sealed "
                f"row whose recorded worktree {recorded} ({kind}) still discovers the "
                f"repository the probe sealed was not pruned; the first apply must reach "
                f"ACTIVE, got: {exc}"
            ) from exc
    assert result["state"] == "ACTIVE"
    assert result["repositories"] == [row["canonical_repository_identity"]]
    fallback_warnings = [
        str(item.message)
        for item in caught
        if issubclass(item.category, live.SealedWorktreeFallbackWarning)
    ]
    assert not fallback_warnings, (
        "789-RED-ANCHOR::non-worktree-repo-path-spurious-fallback-warning — the "
        f"recorded path {recorded} ({kind}) still discovers the sealed repository, "
        f"nothing was pruned, yet the apply warned: {fallback_warnings}"
    )
    assert live.WriterGenerationLatch.open(recorded).read().generation_state == "ACTIVE"


@_production_dependent
@pytest.mark.parametrize("kind", NON_WORKTREE_KINDS)
def test_resume_reader_does_not_warn_for_row_recording_non_worktree_repo_path(
    tmp_path: Path, kind: str
) -> None:
    """``_inventory_row_repository`` on a row whose worktree is a bare
    repository, ``<repo>/.git`` or ``<repo>/.git/objects`` returns the recorded
    path with no fallback warning."""
    recorded = _non_worktree_repo_path(tmp_path, kind)
    _assert_non_worktree_fixture(recorded, kind)
    inventory = _probe(tmp_path, recorded)
    row = _sealed_row(inventory)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = live._inventory_row_repository(row)
    assert resolved.resolve() == recorded, (
        "789-RED-ANCHOR::non-worktree-repo-path-reader-substitutes — the resume reader "
        f"replaced the recorded path {recorded} ({kind}), which still discovers the "
        f"sealed repository, with {resolved}"
    )
    fallback_warnings = [
        str(item.message)
        for item in caught
        if issubclass(item.category, live.SealedWorktreeFallbackWarning)
    ]
    assert not fallback_warnings, (
        "789-RED-ANCHOR::non-worktree-repo-path-reader-warns — the resume reader warned "
        f"about a fallback for {recorded} ({kind}), which still discovers the sealed "
        f"repository: {fallback_warnings}"
    )


@_production_dependent
def test_interrupted_onboarding_resumes_for_row_recording_git_objects_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """codex r3: an onboarding sealed with ``<repo>/.git/objects`` recorded as
    the row path and interrupted after its inventory seal must resume to
    ACTIVE through ``_revalidate_bootstrap_sources`` -- the path was never
    pruned, so the resume reader must use it as recorded (no fallback
    warning) and the identity must still match."""
    main = _git_repo(tmp_path / "main")
    recorded = (main / ".git" / "objects").resolve()
    _assert_non_worktree_fixture(recorded, "gitobjects")
    inventory = _probe(tmp_path, recorded)
    row = _sealed_row(inventory)
    assert Path(row["worktree"]).resolve() == recorded

    with monkeypatch.context() as patcher:
        _crash_at_proof_phase(patcher, "before_receipt_write", "crash-after-onboarding-seal")
        # ``LegacyCutoverConflict`` is a ``RuntimeError``: name it first so a
        # guard refusal surfaces as the anchor, not as a regex mismatch.
        try:
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
        except live.LegacyCutoverConflict as exc:
            raise AssertionError(
                "789-RED-ANCHOR::interrupted-onboarding-git-objects-first-apply — the first "
                f"apply refused the sealed row for {recorded} before it could even reach "
                f"the onboarding seal; got: {exc}"
            ) from exc
        except RuntimeError as exc:
            assert "crash-after-onboarding-seal" in str(exc), exc
        else:
            raise AssertionError("the injected crash did not fire")
    assert _onboarding_inventory_path(row).exists(), "did not reach bootstrap_in_progress"
    assert live.load_partition_receipt(live.repository_snapshot(main).store_root) is None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )
        except live.LegacyCutoverConflict as exc:
            raise AssertionError(
                "789-RED-ANCHOR::interrupted-onboarding-git-objects-resume — an onboarding "
                f"sealed with {recorded} recorded and interrupted after its inventory seal "
                f"must resume; the path still discovers the sealed repository; got: {exc}"
            ) from exc
    assert result["state"] == "ACTIVE"
    assert result["repositories"] == [row["canonical_repository_identity"]]
    fallback_warnings = [
        str(item.message)
        for item in caught
        if issubclass(item.category, live.SealedWorktreeFallbackWarning)
    ]
    assert not fallback_warnings, (
        "789-RED-ANCHOR::interrupted-onboarding-git-objects-warns — nothing was pruned, "
        f"yet the resume warned: {fallback_warnings}"
    )
    receipt = live.load_partition_receipt(live.repository_snapshot(main).store_root)
    assert receipt is not None and receipt.zero_source
    assert live.WriterGenerationLatch.open(main).read().generation_state == "ACTIVE"


@_production_dependent
def test_first_apply_refuses_row_replaced_by_plain_dir(tmp_path: Path) -> None:
    """The discovery-based health check must not widen to "the path exists":
    a pruned worktree replaced by a plain directory before the first apply is
    still pruned and must refuse with the re-probe remedy."""
    main = _git_repo(tmp_path / "main")
    linked = _linked_worktree(main, tmp_path / "linked", "linked")
    inventory = _probe(tmp_path, linked)
    row = _sealed_row(inventory)
    _remove_linked_worktree(main, linked)
    linked.mkdir()
    assert not live.is_git_repository(linked)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", live.SealedWorktreeFallbackWarning)
        try:
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
        except live.LegacyCutoverConflict as exc:
            message = str(exc)
        else:
            raise AssertionError(
                "789-RED-ANCHOR::first-apply-plain-dir-accepted — a first apply whose "
                f"sealed worktree {linked} was pruned and replaced by a plain directory "
                "must refuse; a directory that exists is not a repository"
            )
    assert "before its first apply" in message and "re-run the zero-history probe" in message, (
        f"789-RED-ANCHOR::first-apply-plain-dir-not-actionable — got: {message}"
    )
    assert row["canonical_repository_identity"] in message
    assert not (tmp_path / "authority" / "ACTIVE_BOOTSTRAP").exists()
