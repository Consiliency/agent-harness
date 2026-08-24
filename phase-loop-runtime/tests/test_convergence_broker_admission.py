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
    import subprocess
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

    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.verbs import publish_committed_branch_idempotency_key
    from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, ReadmitAdmissionBinding
    from phase_loop_runtime.publishing import prepare_publish_transaction
    from test_fabpub_shared_epoch import (
        _authorized_publish_fixture,
        _publish_transaction_request,
        _service,
        _CountingAdapter,
        _authority_preimage,
    )

    # 1. Create activated real repository & real durable/resumed FABPUB transaction
    repo_dir, transaction, identity, store_root = _authorized_publish_fixture(
        tmp_path, name="first-hop-readmit"
    )
    adapter = _CountingAdapter()
    store = LinearizableAdmissionStore(store_root, lambda _: True)
    svc = _service(store_root, adapter, store=store)

    # 2. Seed prior publish admission through real BrokerService.execute(PreAdmissionEnvelope)
    branch = "feat/x"
    pub_req = _publish_transaction_request(identity, branch, transaction, repo_dir)
    envelope = pub_req.admission
    pub_outcome = svc.execute(pub_req)
    assert pub_outcome.accepted, "prior publish transaction must be admitted"
    initial_count = len(store.replay())
    assert initial_count == 1

    # 3. Prove durable prior admission key equals recomputed publish_committed_branch_idempotency_key
    prior_admission = store.replay()[0]
    recomputed_key = publish_committed_branch_idempotency_key(
        identity, branch, transaction.committed_head_sha
    )
    assert prior_admission.request.idempotency_key == (
        f"publish_committed_branch\0{recomputed_key}"
    )

    # 4. Bind checkpoint root and create real descendant proposed commit
    ckpt = transaction.checkpoint_root
    train_id = envelope.train_id
    node_id = envelope.node_id
    roadmap_digest = envelope.roadmap_digest
    (ckpt / "train.json").write_text(
        f'{{"train_id": "{train_id}", "repository": "{identity}"}}',
        encoding="utf-8",
    )
    (ckpt / f"{node_id}.json").write_text(
        f'{{"node_id": "{node_id}"}}', encoding="utf-8"
    )

    (repo_dir / "a.py").write_text("v2 advance\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "advance 1"], check=True)
    proposed_head_sha1 = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    # Negative arms: absent-transaction, key mismatch, node mismatch (structural validation)
    ckpt_no_txn = tmp_path / "ckpt_no_txn"
    ckpt_no_txn.mkdir()
    (ckpt_no_txn / "train.json").write_text(f'{{"train_id": "{train_id}", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt_no_txn / f"{node_id}.json").write_text(f'{{"node_id": "{node_id}"}}', encoding="utf-8")
    auth_no_txn = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt_no_txn), branch=branch, base="main",
        prior_head_sha=transaction.committed_head_sha, proposed_head_sha=proposed_head_sha1, train_id=train_id,
        node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)transaction|absent|missing|publish"):
        store.admit_next(auth_no_txn)
    assert len(store.replay()) == initial_count

    ckpt_key_mismatch = tmp_path / "ckpt_key_mismatch"
    ckpt_key_mismatch.mkdir()
    (ckpt_key_mismatch / "train.json").write_text(f'{{"train_id": "{train_id}", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt_key_mismatch / f"{node_id}.json").write_text(f'{{"node_id": "{node_id}"}}', encoding="utf-8")
    prepare_publish_transaction(
        repo_dir, owned_paths=("a.py",), checkpoint_root=ckpt_key_mismatch, branch="feat/other",
        envelope_authority_preimage=_authority_preimage(identity, "feat/other"), node_id=node_id
    )
    auth_key_mismatch = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt_key_mismatch), branch=branch, base="main",
        prior_head_sha=transaction.committed_head_sha, proposed_head_sha=proposed_head_sha1, train_id=train_id,
        node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)key|mismatch|idempotency|branch"):
        store.admit_next(auth_key_mismatch)
    assert len(store.replay()) == initial_count

    ckpt_node_mismatch = tmp_path / "ckpt_node_mismatch"
    ckpt_node_mismatch.mkdir()
    other_node = "other_node"
    (ckpt_node_mismatch / "train.json").write_text(f'{{"train_id": "{train_id}", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt_node_mismatch / f"{other_node}.json").write_text(f'{{"node_id": "{other_node}"}}', encoding="utf-8")
    prepare_publish_transaction(
        repo_dir, owned_paths=("a.py",), checkpoint_root=ckpt_node_mismatch, branch=branch,
        envelope_authority_preimage=_authority_preimage(identity, branch), node_id=other_node
    )
    auth_node_mismatch = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt_node_mismatch), branch=branch, base="main",
        prior_head_sha=transaction.committed_head_sha, proposed_head_sha=proposed_head_sha1, train_id=train_id,
        node_id=other_node, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)node"):
        store.admit_next(auth_node_mismatch)
    assert len(store.replay()) == initial_count

    # 5. Valid first-hop readmission
    auth_hop1 = DeltaReadmitAuthority(
        repository=identity,
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt),
        branch=branch,
        base="main",
        prior_head_sha=transaction.committed_head_sha,
        proposed_head_sha=proposed_head_sha1,
        train_id=train_id,
        node_id=node_id,
        fab_run_id="run1",
        roadmap_digest=roadmap_digest,
        provenance_digest="p" * 64,
        owned_scope=("a.py",),
    )
    rec1 = store.admit_next(auth_hop1)
    assert len(store.replay()) == initial_count + 1
    assert rec1.epoch == initial_count + 1
    assert rec1.binding == ReadmitAdmissionBinding(
        prior_head_sha=transaction.committed_head_sha,
        proposed_head_sha=proposed_head_sha1,
        node_id=node_id,
        owned_scope=("a.py",),
        authority_digest=auth_hop1.authority_digest,
    )

    # 6. Valid chained hop2 readmission
    (repo_dir / "a.py").write_text("v3 advance\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "advance 2"], check=True)
    proposed_head_sha2 = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    auth_hop2 = DeltaReadmitAuthority(
        repository=identity,
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt),
        branch=branch,
        base="main",
        prior_head_sha=proposed_head_sha1,
        proposed_head_sha=proposed_head_sha2,
        train_id=train_id,
        node_id=node_id,
        fab_run_id="run1",
        roadmap_digest=roadmap_digest,
        provenance_digest="p" * 64,
        owned_scope=("a.py",),
    )
    rec2 = store.admit_next(auth_hop2)
    assert len(store.replay()) == initial_count + 2
    cnt = len(store.replay())

    # Rejection matrix: non-vacuous arms with exact matches & unchanged count
    # Arm 1: First-hop wrong-node on an isolated store whose prior is real published transaction
    repo_iso, txn_iso, identity_iso, store_iso_root = _authorized_publish_fixture(
        tmp_path, name="iso-readmit"
    )
    store_iso = LinearizableAdmissionStore(store_iso_root, lambda _: True)
    svc_iso = _service(store_iso_root, _CountingAdapter(), store=store_iso)
    svc_iso.execute(_publish_transaction_request(identity_iso, branch, txn_iso, repo_iso))
    cnt_iso = len(store_iso.replay())

    envelope_iso = _publish_transaction_request(identity_iso, branch, txn_iso, repo_iso).admission
    ckpt_iso = txn_iso.checkpoint_root
    (ckpt_iso / "train.json").write_text(f'{{"train_id": "{envelope_iso.train_id}", "repository": "{identity_iso}"}}', encoding="utf-8")
    (ckpt_iso / "wrong_node.json").write_text('{"node_id": "wrong_node"}', encoding="utf-8")

    auth_first_wrong_node = DeltaReadmitAuthority(
        repository=identity_iso, adapter_worktree=str(repo_iso),
        checkpoint_root=str(ckpt_iso), branch=branch, base="main",
        prior_head_sha=txn_iso.committed_head_sha, proposed_head_sha="f" * 40, train_id=envelope_iso.train_id,
        node_id="wrong_node", fab_run_id="run1", roadmap_digest=envelope_iso.roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)node"):
        store_iso.admit_next(auth_first_wrong_node)
    assert len(store_iso.replay()) == cnt_iso

    # Arm 2: Chained wrong-node (FR-R7-06: write matching wrong_node.json so structural validation passes)
    (ckpt / "wrong_node.json").write_text('{"node_id": "wrong_node"}', encoding="utf-8")
    auth_chained_wrong_node = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt), branch=branch, base="main",
        prior_head_sha=proposed_head_sha2, proposed_head_sha="f" * 40, train_id=train_id,
        node_id="wrong_node", fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)node"):
        store.admit_next(auth_chained_wrong_node)
    assert len(store.replay()) == cnt

    # Arm 3: Wrong-branch
    auth_wrong_branch = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt), branch="feat/wrong", base="main",
        prior_head_sha=proposed_head_sha2, proposed_head_sha="f" * 40, train_id=train_id,
        node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)branch"):
        store.admit_next(auth_wrong_branch)
    assert len(store.replay()) == cnt

    # Arm 4: Wrong-scope
    auth_wrong_scope = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt), branch=branch, base="main",
        prior_head_sha=proposed_head_sha2, proposed_head_sha="f" * 40, train_id=train_id,
        node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("unadmitted_scope",)
    )
    with pytest.raises(PermissionError, match=r"(?i)scope"):
        store.admit_next(auth_wrong_scope)
    assert len(store.replay()) == cnt

    # Arm 5: Stale prior head
    auth_stale = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt), branch=branch, base="main",
        prior_head_sha=transaction.committed_head_sha, proposed_head_sha="f" * 40, train_id=train_id,
        node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)stale|prior"):
        store.admit_next(auth_stale)
    assert len(store.replay()) == cnt

    # Arm 6: Never-admitted / forged prior head
    auth_forged = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt), branch=branch, base="main",
        prior_head_sha="f" * 40, proposed_head_sha="g" * 40, train_id=train_id,
        node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64,
        owned_scope=("a.py",)
    )
    with pytest.raises(PermissionError, match=r"(?i)prior|unadmitted|unknown|forged"):
        store.admit_next(auth_forged)
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

    main_record = store_main.admit(
        AdmissionRequest("main", 1, "f-main", "d-main", "v1", "scope", "main-key")
    )
    linked_record = store_linked.admit(
        AdmissionRequest("linked", 2, "f-linked", "d-linked", "v1", "scope", "linked-key")
    )

    replay_main = store_main.replay()
    replay_linked = store_linked.replay()
    assert [record.epoch for record in (main_record, linked_record)] == [1, 2]
    assert replay_main == replay_linked == [main_record, linked_record]
    assert [record.request.idempotency_key for record in replay_main] == ["main-key", "linked-key"]
