from pytest import skip
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.contracts import AdmissionRequest

from _fabreadmit_tdd_guard import (
    FABREADMIT_SKIP_REASON,
    fabreadmit_capability_active,
    fabreadmit_require,
    fabreadmit_symbol,
    fabreadmit_this_nodeid,
)


def test_admission_replays_idempotently(tmp_path):
    request = AdmissionRequest("a", 1, "f", "d", "v", "scope", "key")
    store = LinearizableAdmissionStore(tmp_path, lambda _: True)
    assert store.admit(request) == store.admit(request)
    assert len(store.replay()) == 1


def _exec_behavioral_red_node(request, fn):
    valid = False
    try:
        fn()
        valid = True
    except Exception:
        valid = False
    fabreadmit_require(fabreadmit_this_nodeid(request), valid)


def test_fabreadmit_prior_record_predicate_and_chained_readmit_binding(request, tmp_path):
    """Prior-record predicate under admission lock & ReadmitAdmissionBinding.v1."""
    import pytest
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    def _run_test():
        from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
        from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, ReadmitAdmissionBinding

        store = LinearizableAdmissionStore(tmp_path / "admissions", lambda _: True)
        initial_count = len(store.replay())

        # Valid first-hop admission
        auth_hop1 = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness",
            adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"),
            branch="feat/x",
            base="main",
            prior_head_sha="a" * 40,
            proposed_head_sha="b" * 40,
            train_id="train1",
            node_id="n1",
            fab_run_id="run1",
            roadmap_digest="d" * 64,
            provenance_digest="p" * 64,
            owned_scope=("pkg",),
        )
        rec1 = store.admit_next(auth_hop1)
        assert len(store.replay()) == initial_count + 1
        assert rec1.binding == ReadmitAdmissionBinding(
            prior_head_sha="a" * 40,
            proposed_head_sha="b" * 40,
            node_id="n1",
            owned_scope=("pkg",),
            authority_digest=auth_hop1.authority_digest,
        )

        # Valid chained hop2
        auth_hop2 = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness",
            adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"),
            branch="feat/x",
            base="main",
            prior_head_sha="b" * 40,
            proposed_head_sha="c" * 40,
            train_id="train1",
            node_id="n1",
            fab_run_id="run1",
            roadmap_digest="d" * 64,
            provenance_digest="p" * 64,
            owned_scope=("pkg",),
        )
        rec2 = store.admit_next(auth_hop2)
        assert len(store.replay()) == initial_count + 2

        # Rejection matrix: 6 invalid prior arms (assert denial + unchanged record count)
        cnt = len(store.replay())

        # 1. Unrelated prior head
        auth_unrelated = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"), branch="feat/x", base="main",
            prior_head_sha="deadbeef" * 5, proposed_head_sha="e" * 40, train_id="train1",
            node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
            owned_scope=("pkg",)
        )
        with pytest.raises(PermissionError):
            store.admit_next(auth_unrelated)
        assert len(store.replay()) == cnt

        # 2. Forged prior
        auth_forged = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"), branch="feat/x", base="main",
            prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
            node_id="n1", fab_run_id="run1", roadmap_digest="wrong" * 12 + "1234", provenance_digest="p" * 64,
            owned_scope=("pkg",)
        )
        with pytest.raises(PermissionError):
            store.admit_next(auth_forged)
        assert len(store.replay()) == cnt

        # 3. Wrong-branch prior
        auth_wrong_branch = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"), branch="feat/wrong", base="main",
            prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
            node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
            owned_scope=("pkg",)
        )
        with pytest.raises(PermissionError):
            store.admit_next(auth_wrong_branch)
        assert len(store.replay()) == cnt

        # 4. Wrong-node prior
        auth_wrong_node = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"), branch="feat/x", base="main",
            prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
            node_id="wrong_node", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
            owned_scope=("pkg",)
        )
        with pytest.raises(PermissionError):
            store.admit_next(auth_wrong_node)
        assert len(store.replay()) == cnt

        # 5. Wrong-scope prior
        auth_wrong_scope = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"), branch="feat/x", base="main",
            prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
            node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
            owned_scope=("unadmitted_scope",)
        )
        with pytest.raises(PermissionError):
            store.admit_next(auth_wrong_scope)
        assert len(store.replay()) == cnt

        # 6. Stale prior head
        auth_stale = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"), branch="feat/x", base="main",
            prior_head_sha="a" * 40, proposed_head_sha="f" * 40, train_id="train1",
            node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
            owned_scope=("pkg",)
        )
        with pytest.raises(PermissionError):
            store.admit_next(auth_stale)
        assert len(store.replay()) == cnt

    _exec_behavioral_red_node(request, _run_test)


def test_fabreadmit_checkpoint_root_validation(request, tmp_path):
    """Checkpoint root validation: reject missing, relative, wrong-train, wrong-node, repo-mismatch."""
    import pytest
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    def _run_test():
        from phase_loop_runtime.convergence.broker.admission import validate_checkpoint_root

        valid_ckpt = tmp_path / "valid_ckpt"
        valid_ckpt.mkdir()
        (valid_ckpt / "train.json").write_text('{"train_id": "train1", "repository": "Consiliency/agent-harness"}', encoding="utf-8")
        (valid_ckpt / "n1.json").write_text('{"node_id": "n1"}', encoding="utf-8")

        # Positive control
        assert validate_checkpoint_root(
            checkpoint_root=str(valid_ckpt),
            repository="Consiliency/agent-harness",
            train_id="train1",
            node_id="n1",
        ) is True

        # Denial 1: Missing checkpoint root directory
        with pytest.raises(ValueError):
            validate_checkpoint_root(
                checkpoint_root=str(tmp_path / "missing_ckpt"),
                repository="Consiliency/agent-harness",
                train_id="train1",
                node_id="n1",
            )

        # Denial 2: Relative checkpoint root path
        with pytest.raises(ValueError):
            validate_checkpoint_root(
                checkpoint_root="relative/ckpt",
                repository="Consiliency/agent-harness",
                train_id="train1",
                node_id="n1",
            )

        # Denial 3: Wrong-train checkpoint root
        with pytest.raises(ValueError):
            validate_checkpoint_root(
                checkpoint_root=str(valid_ckpt),
                repository="Consiliency/agent-harness",
                train_id="wrong_train",
                node_id="n1",
            )

        # Denial 4: Wrong-node checkpoint root
        with pytest.raises(ValueError):
            validate_checkpoint_root(
                checkpoint_root=str(valid_ckpt),
                repository="Consiliency/agent-harness",
                train_id="train1",
                node_id="wrong_node",
            )

        # Denial 5: Repository-mismatched checkpoint root
        with pytest.raises(ValueError):
            validate_checkpoint_root(
                checkpoint_root=str(valid_ckpt),
                repository="Consiliency/other-repo",
                train_id="train1",
                node_id="n1",
            )

    _exec_behavioral_red_node(request, _run_test)


def test_fabreadmit_linked_worktrees_share_canonical_repository_allocator(request, tmp_path):
    """Linked worktrees and distinct train roots share the same repository admission store."""
    import subprocess
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    def _run_test():
        from phase_loop_runtime.convergence.broker.admission import get_canonical_repository_store

        main_repo = tmp_path / "main_repo"
        main_repo.mkdir()
        subprocess.run(["git", "init", "-q", str(main_repo)], check=True)
        subprocess.run(["git", "-C", str(main_repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(main_repo), "config", "user.name", "Test"], check=True)
        (main_repo / "a.py").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(main_repo), "add", "a.py"], check=True)
        subprocess.run(["git", "-C", str(main_repo), "commit", "-q", "-m", "init"], check=True)

        linked_wt = tmp_path / "linked_worktree"
        subprocess.run(["git", "-C", str(main_repo), "worktree", "add", "-q", str(linked_wt), "HEAD"], check=True)

        train_root_1 = tmp_path / "train_root_1"
        train_root_2 = tmp_path / "train_root_2"
        train_root_1.mkdir()
        train_root_2.mkdir()

        store_main = get_canonical_repository_store(main_repo, checkpoint_root=train_root_1)
        store_linked = get_canonical_repository_store(linked_wt, checkpoint_root=train_root_2)

        assert store_main is not None and store_linked is not None
        assert store_main.canonical_repository == store_linked.canonical_repository
        assert store_main.store_dir.resolve() == store_linked.store_dir.resolve()

    _exec_behavioral_red_node(request, _run_test)
