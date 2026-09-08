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
INCIDENT_TEXT = "No such file"


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

    assert second == first, "resume after prune must report the same ACTIVE result"
    assert second["repositories"] == [row["canonical_repository_identity"]]
    receipt = live.load_partition_receipt(live.repository_snapshot(main).store_root)
    assert receipt is not None
    assert receipt.canonical_repository_identity == row["canonical_repository_identity"]
    assert live.WriterGenerationLatch.open(main).read().generation_state == "ACTIVE"
    assert _journal_bytes(tmp_path) == journal_before, "a resume writes no new journal state"

    signals = _fallback_signals(caught, caplog, second)
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
