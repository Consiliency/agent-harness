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


def test_fabreadmit_prior_record_predicate_and_chained_readmit_binding(request, tmp_path):
    """Prior-record predicate under admission lock & ReadmitAdmissionBinding.v1."""
    import pytest
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    binding_symbol = fabreadmit_symbol(
        "phase_loop_runtime.convergence.contracts", "ReadmitAdmissionBinding"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        binding_symbol is not None,
        "ReadmitAdmissionBinding missing in phase_loop_runtime.convergence.contracts",
    )

    from phase_loop_runtime.convergence.broker.admission import (
        LinearizableAdmissionStore,
        LegacyBrokerCutoverManifest,
        run_legacy_broker_cutover,
    )
    from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, ReadmitAdmissionBinding

    # 1. Setup validated checkpoint root (FR-SL0-05)
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "train.json").write_text('{"train_id": "train1", "repository": "Consiliency/agent-harness"}', encoding="utf-8")
    (ckpt / "n1.json").write_text('{"node_id": "n1"}', encoding="utf-8")

    # 2. Setup activated partition (FR-SL0-04)
    cutover_dir = tmp_path / "cutover"
    cutover_dir.mkdir()
    manifest = LegacyBrokerCutoverManifest(
        repository="Consiliency/agent-harness",
        prior_head_sha="a" * 40,
        checkpoint_root=str(ckpt),
    )
    receipt = run_legacy_broker_cutover(manifest, cutover_dir)
    receipt.activate()

    partition_dir = tmp_path / "partition"
    partition_dir.mkdir()
    store = LinearizableAdmissionStore(partition_dir, lambda _: True)

    # 3. Create durable first-hop publish transaction at checkpoint root
    pub_req = AdmissionRequest(
        attempt_id="att1",
        epoch=1,
        fence_token="fence1",
        approval_digest="d" * 64,
        prior_predicate="a" * 40,
        owned_scope="pkg",
        idempotency_key="key1",
    )
    store.admit(pub_req)
    initial_count = len(store.replay())

    # 4. Valid first-hop readmission
    auth_hop1 = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness",
        adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt),
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

    # Valid chained hop2 readmission
    auth_hop2 = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness",
        adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt),
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

    cnt = len(store.replay())

    # Rejection matrix (FR-SL0-05): exact reason matching & unchanged count
    # Arm 1: First-hop wrong-node
    auth_first_wrong_node = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt), branch="feat/x", base="main",
        prior_head_sha="a" * 40, proposed_head_sha="f" * 40, train_id="train1",
        node_id="wrong_node", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
        owned_scope=("pkg",)
    )
    with pytest.raises(PermissionError, match=r"(?i)node|prior"):
        store.admit_next(auth_first_wrong_node)
    assert len(store.replay()) == cnt

    # Arm 2: Chained wrong-node
    auth_chained_wrong_node = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt), branch="feat/x", base="main",
        prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
        node_id="wrong_node", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
        owned_scope=("pkg",)
    )
    with pytest.raises(PermissionError, match=r"(?i)node|prior"):
        store.admit_next(auth_chained_wrong_node)
    assert len(store.replay()) == cnt

    # Arm 3: Wrong-branch
    auth_wrong_branch = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt), branch="feat/wrong", base="main",
        prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
        node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
        owned_scope=("pkg",)
    )
    with pytest.raises(PermissionError, match=r"(?i)branch|prior"):
        store.admit_next(auth_wrong_branch)
    assert len(store.replay()) == cnt

    # Arm 4: Wrong-scope
    auth_wrong_scope = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt), branch="feat/x", base="main",
        prior_head_sha="c" * 40, proposed_head_sha="f" * 40, train_id="train1",
        node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
        owned_scope=("unadmitted_scope",)
    )
    with pytest.raises(PermissionError, match=r"(?i)scope|prior"):
        store.admit_next(auth_wrong_scope)
    assert len(store.replay()) == cnt

    # Arm 5: Stale prior head
    auth_stale = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness", adapter_worktree=str(tmp_path / "repo"),
        checkpoint_root=str(ckpt), branch="feat/x", base="main",
        prior_head_sha="a" * 40, proposed_head_sha="f" * 40, train_id="train1",
        node_id="n1", fab_run_id="run1", roadmap_digest="d" * 64, provenance_digest="p" * 64,
        owned_scope=("pkg",)
    )
    with pytest.raises(PermissionError, match=r"(?i)stale|prior"):
        store.admit_next(auth_stale)
    assert len(store.replay()) == cnt


def test_fabreadmit_checkpoint_root_validation(request, tmp_path):
    """Checkpoint root validation: reject missing, relative, wrong-train, wrong-node, repo-mismatch."""
    import pytest
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    validator_symbol = fabreadmit_symbol(
        "phase_loop_runtime.convergence.broker.admission", "validate_checkpoint_root"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        validator_symbol is not None,
        "validate_checkpoint_root missing in phase_loop_runtime.convergence.broker.admission",
    )

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
    with pytest.raises(ValueError, match=r"(?i)missing|directory|exist"):
        validate_checkpoint_root(
            checkpoint_root=str(tmp_path / "missing_ckpt"),
            repository="Consiliency/agent-harness",
            train_id="train1",
            node_id="n1",
        )

    # Denial 2: Relative checkpoint root path
    with pytest.raises(ValueError, match=r"(?i)relative|absolute"):
        validate_checkpoint_root(
            checkpoint_root="relative/ckpt",
            repository="Consiliency/agent-harness",
            train_id="train1",
            node_id="n1",
        )

    # Denial 3: Wrong-train checkpoint root
    with pytest.raises(ValueError, match=r"(?i)train"):
        validate_checkpoint_root(
            checkpoint_root=str(valid_ckpt),
            repository="Consiliency/agent-harness",
            train_id="wrong_train",
            node_id="n1",
        )

    # Denial 4: Wrong-node checkpoint root
    with pytest.raises(ValueError, match=r"(?i)node"):
        validate_checkpoint_root(
            checkpoint_root=str(valid_ckpt),
            repository="Consiliency/agent-harness",
            train_id="train1",
            node_id="wrong_node",
        )

    # Denial 5: Repository-mismatched checkpoint root
    with pytest.raises(ValueError, match=r"(?i)repository|mismatch"):
        validate_checkpoint_root(
            checkpoint_root=str(valid_ckpt),
            repository="Consiliency/other-repo",
            train_id="train1",
            node_id="n1",
        )


def test_fabreadmit_linked_worktrees_share_canonical_repository_allocator(request, tmp_path):
    """Linked worktrees and distinct train roots share the same repository admission store."""
    import subprocess
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    resolver_symbol = fabreadmit_symbol(
        "phase_loop_runtime.convergence.broker.admission", "get_canonical_repository_store"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        resolver_symbol is not None,
        "get_canonical_repository_store missing in phase_loop_runtime.convergence.broker.admission",
    )

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
