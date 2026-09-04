"""FABREADMIT (v10) broker admission-only tests — SL-0, immutable contract.
"""

from __future__ import annotations

import subprocess
import pytest

from _fabreadmit_tdd_guard import (
    FABREADMIT_SKIP_REASON,
    fabreadmit_capability_active,
    fabreadmit_require,
    fabreadmit_symbol,
    fabreadmit_this_nodeid,
    test_fabreadmit_guard_inventory_and_digests as _check_guard_inventory,
)


def test_fabreadmit_guard_inventory_integrity():
    """Collect the always-green frozen-inventory control with the SL-0 suite."""
    import hashlib

    from test_fab_activation_promotion import (
        _SUPPORTED_PUBLISHERS_DIGEST,
        _SUPPORTED_PUBLISHERS_FROZEN_SET,
    )

    _check_guard_inventory()
    assert hashlib.sha256(
        ("\n".join(sorted(_SUPPORTED_PUBLISHERS_FROZEN_SET)) + "\n").encode("utf-8")
    ).hexdigest() == _SUPPORTED_PUBLISHERS_DIGEST


class _CountingAdapter:
    def __init__(self):
        self.calls = 0

    def execute(self, request):
        self.calls += 1
        raise RuntimeError("Provider adapter must never be called on readmission")


def test_fabreadmit_broker_authority_receipt_contract(request):
    """IF-0-FABREADMIT-1 authority and receipt shape contract."""
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    authority_symbol = fabreadmit_symbol(
        "phase_loop_runtime.convergence.contracts", "DeltaReadmitAuthority"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        authority_symbol is not None,
        "DeltaReadmitAuthority missing in phase_loop_runtime.convergence.contracts",
    )

    from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, DeltaReadmitReceipt
    from phase_loop_runtime.convergence.broker.live import BrokerClient

    valid_kwargs = {
        "repository": "Consiliency/agent-harness",
        "adapter_worktree": "/tmp/wt",
        "checkpoint_root": "/tmp/ckpt",
        "branch": "feat/x",
        "base": "main",
        "prior_head_sha": "a" * 40,
        "proposed_head_sha": "b" * 40,
        "train_id": "train1",
        "node_id": "n1",
        "fab_run_id": "run1",
        "roadmap_digest": "d" * 64,
        "provenance_digest": "p" * 64,
        "owned_scope": ("pkg",),
    }

    auth = DeltaReadmitAuthority(**valid_kwargs)

    # Immutability
    with pytest.raises((TypeError, AttributeError)):
        auth.branch = "other"  # type: ignore

    # Forbidden fields (FR-SL0-07): full valid kwargs + 1 forbidden field must fail with unexpected keyword
    for forbidden in ("epoch", "attempt_id", "fence_token", "approval_digest", "idempotency_key"):
        bad_kwargs = dict(valid_kwargs)
        bad_kwargs[forbidden] = "forbidden_val"
        with pytest.raises(TypeError, match=r"unexpected keyword argument"):
            DeltaReadmitAuthority(**bad_kwargs)
        assert not hasattr(auth, forbidden)

    # Receipt instantiation and binding verification
    receipt = DeltaReadmitReceipt(
        repository="Consiliency/agent-harness",
        branch="feat/x",
        prior_head_sha="a" * 40,
        proposed_head_sha="b" * 40,
        allocated_epoch=2,
        attempt_identity="att1",
        authority_digest="auth" * 16,
    )
    assert receipt.repository == "Consiliency/agent-harness"
    assert receipt.allocated_epoch == 2
    assert receipt.authority_digest == "auth" * 16

    assert hasattr(BrokerClient, "readmit_advanced_head")


def test_fabreadmit_broker_rediffs_head_range_and_rejects_scope_escape_without_adapter(request, tmp_path):
    """Broker independently re-diffs prior..proposed, rejects scope escape, calls zero adapters."""
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    verb_symbol = fabreadmit_symbol(
        "phase_loop_runtime.convergence.broker.verbs", "BrokerService.readmit_advanced_head"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        verb_symbol is not None,
        "BrokerService.readmit_advanced_head missing in phase_loop_runtime.convergence.broker.verbs",
    )

    from phase_loop_runtime.convergence.broker.verbs import BrokerService
    from phase_loop_runtime.convergence.broker import live
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
    from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority
    from phase_loop_runtime.publishing import prepare_publish_transaction
    from test_fabpub_shared_epoch import (
        _authorized_publish_fixture,
        _publish_transaction_request,
        _service,
        _CountingAdapter,
        _authority_preimage,
    )

    # 1. FR-R5-01 & FR-R7-01 & FR-R7-02: Empty-store denial arm proving readmission from an empty onboarded store fails with zero appends
    repo_empty, txn_empty, id_empty, root_empty = _authorized_publish_fixture(tmp_path, name="empty-store")
    empty_envelope = _publish_transaction_request(id_empty, "feat/x", txn_empty, repo_empty).admission
    store_empty = LinearizableAdmissionStore(root_empty, lambda _: True)
    pub_empty_adapter = _CountingAdapter()
    svc_empty_pub = BrokerService(store_empty, BrokerEvidenceStore(root_empty), pub_empty_adapter)
    ckpt_empty = txn_empty.checkpoint_root
    (ckpt_empty / "train.json").write_text(f'{{"train_id": "{empty_envelope.train_id}", "repository": "{id_empty}"}}', encoding="utf-8")
    (ckpt_empty / f"{empty_envelope.node_id}.json").write_text(f'{{"node_id": "{empty_envelope.node_id}"}}', encoding="utf-8")
    auth_empty = DeltaReadmitAuthority(
        repository=id_empty, adapter_worktree=str(repo_empty), checkpoint_root=str(ckpt_empty),
        branch="feat/x", base="main", prior_head_sha=txn_empty.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=empty_envelope.train_id, node_id=empty_envelope.node_id, fab_run_id="run1", roadmap_digest=empty_envelope.roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    readmit_empty_adapter = _CountingAdapter()
    svc_empty_readmit = BrokerService(store_empty, BrokerEvidenceStore(root_empty), readmit_empty_adapter)
    with pytest.raises((PermissionError, ValueError), match=r"(?i)prior|unadmitted|unknown|forged|empty"):
        svc_empty_readmit.readmit_advanced_head(auth_empty)
    assert len(store_empty.replay()) == 0
    assert len(readmit_empty_adapter.calls) == 0

    # 2. FR-R5-01 & FR-R7-02: Make unowned.py part of the base, before the
    # admitted candidate.  The positive prior..proposed range may then contain
    # only the owned a.py change; the following escape commit is the sole scope
    # violation.
    repo_dir = tmp_path / "rediff-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test"], check=True)
    (repo_dir / "a.py").write_text("v1\n", encoding="utf-8")
    (repo_dir / "unowned.py").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "a.py", "unowned.py"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "base with unowned path"], check=True)
    bootstrap_inventory = live.probe_zero_history_bootstrap(
        cutover_id="fabreadmit-test-bootstrap",
        authority_root=tmp_path / "fabpub-authority",
        worktrees=(repo_dir,),
        search_roots=(tmp_path,),
    )
    live.bootstrap_zero_history_authority(
        bootstrap_inventory, confirmed_zero_history=True
    )
    identity = live.canonical_repository_identity(repo_dir)
    store_root = live.repository_broker_namespace(repo_dir)
    branch = "feat/x"
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "-q", "-b", branch], check=True)
    (repo_dir / "a.py").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "a.py"], check=True)
    transaction = prepare_publish_transaction(
        repo_dir,
        owned_paths=("a.py",),
        checkpoint_root=tmp_path / "coord" / "rediff-repo",
        branch=branch,
        envelope_authority_preimage=_authority_preimage(identity, branch),
    )
    transaction.resume()
    pub_adapter = _CountingAdapter()
    store = LinearizableAdmissionStore(store_root, lambda _: True)
    evidence = BrokerEvidenceStore(store_root)
    pub_service = _service(store_root, pub_adapter, store=store)

    pub_req = _publish_transaction_request(identity, branch, transaction, repo_dir)
    admitted_envelope = pub_req.admission
    train_id = admitted_envelope.train_id
    node_id = admitted_envelope.node_id
    roadmap_digest = admitted_envelope.roadmap_digest
    pub_res = pub_service.execute(pub_req)
    assert pub_res.accepted, "prior publish transaction must be admitted"
    assert len(store.replay()) == 1

    # FR-R7-02: Use distinct adapter for readmission control
    readmit_adapter = _CountingAdapter()
    readmit_service = BrokerService(store, evidence, readmit_adapter)

    # FR-R5-04 & FR-R7-01: Valid checkpoint root at transaction's checkpoint root
    ckpt = transaction.checkpoint_root
    (ckpt / "train.json").write_text(f'{{"train_id": "{train_id}", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt / f"{node_id}.json").write_text(f'{{"node_id": "{node_id}"}}', encoding="utf-8")

    # FR-R5-04: Readmission denial matrix for structural checkpoint root validation
    # Missing root
    auth_missing_root = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir), checkpoint_root=str(tmp_path / "missing_ckpt"),
        branch=branch, base="main", prior_head_sha=transaction.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=train_id, node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    with pytest.raises((PermissionError, ValueError), match=r"(?i)checkpoint|missing|directory|exist"):
        readmit_service.readmit_advanced_head(auth_missing_root)
    assert len(store.replay()) == 1
    assert len(readmit_adapter.calls) == 0

    # Relative root
    auth_rel_root = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir), checkpoint_root="relative/ckpt",
        branch=branch, base="main", prior_head_sha=transaction.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=train_id, node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    with pytest.raises((PermissionError, ValueError), match=r"(?i)relative|absolute"):
        readmit_service.readmit_advanced_head(auth_rel_root)
    assert len(store.replay()) == 1
    assert len(readmit_adapter.calls) == 0

    # Wrong train root
    ckpt_wrong_train = tmp_path / "ckpt_wrong_train"
    ckpt_wrong_train.mkdir()
    (ckpt_wrong_train / "train.json").write_text(f'{{"train_id": "wrong_train", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt_wrong_train / f"{node_id}.json").write_text(f'{{"node_id": "{node_id}"}}', encoding="utf-8")
    auth_wrong_train = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir), checkpoint_root=str(ckpt_wrong_train),
        branch=branch, base="main", prior_head_sha=transaction.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=train_id, node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    with pytest.raises((PermissionError, ValueError), match=r"(?i)train"):
        readmit_service.readmit_advanced_head(auth_wrong_train)
    assert len(store.replay()) == 1
    assert len(readmit_adapter.calls) == 0

    # Wrong node root
    ckpt_wrong_node = tmp_path / "ckpt_wrong_node"
    ckpt_wrong_node.mkdir()
    (ckpt_wrong_node / "train.json").write_text(f'{{"train_id": "{train_id}", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt_wrong_node / "other_node.json").write_text('{"node_id": "other_node"}', encoding="utf-8")
    auth_wrong_node = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir), checkpoint_root=str(ckpt_wrong_node),
        branch=branch, base="main", prior_head_sha=transaction.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=train_id, node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    with pytest.raises((PermissionError, ValueError), match=r"(?i)node"):
        readmit_service.readmit_advanced_head(auth_wrong_node)
    assert len(store.replay()) == 1
    assert len(readmit_adapter.calls) == 0

    # Repository identity mismatch
    ckpt_repo_mismatch = tmp_path / "ckpt_repo_mismatch"
    ckpt_repo_mismatch.mkdir()
    (ckpt_repo_mismatch / "train.json").write_text(f'{{"train_id": "{train_id}", "repository": "Other/repo"}}', encoding="utf-8")
    (ckpt_repo_mismatch / f"{node_id}.json").write_text(f'{{"node_id": "{node_id}"}}', encoding="utf-8")
    auth_repo_mismatch = DeltaReadmitAuthority(
        repository=identity, adapter_worktree=str(repo_dir), checkpoint_root=str(ckpt_repo_mismatch),
        branch=branch, base="main", prior_head_sha=transaction.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=train_id, node_id=node_id, fab_run_id="run1", roadmap_digest=roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    with pytest.raises((PermissionError, ValueError), match=r"(?i)repository|mismatch"):
        readmit_service.readmit_advanced_head(auth_repo_mismatch)
    assert len(store.replay()) == 1
    assert len(readmit_adapter.calls) == 0

    # 3. Commit 1 (in scope): touches a.py
    (repo_dir / "a.py").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "in scope"], check=True)
    in_scope_sha = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    # Commit 2 (scope escape): touches unowned.py
    (repo_dir / "unowned.py").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "escape"], check=True)
    escape_sha = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    # Positive in-scope execution
    in_scope_auth = DeltaReadmitAuthority(
        repository=identity,
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt),
        branch=branch,
        base="main",
        prior_head_sha=transaction.committed_head_sha,
        proposed_head_sha=in_scope_sha,
        train_id=train_id,
        node_id=node_id,
        fab_run_id="run1",
        roadmap_digest=roadmap_digest,
        provenance_digest="p" * 64,
        owned_scope=("a.py",),
    )
    res_in = readmit_service.readmit_advanced_head(in_scope_auth)
    assert res_in is not None
    assert res_in.allocated_epoch == 2
    assert len(readmit_adapter.calls) == 0

    # Scope-escape execution
    out_of_scope_auth = DeltaReadmitAuthority(
        repository=identity,
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt),
        branch=branch,
        base="main",
        prior_head_sha=in_scope_sha,
        proposed_head_sha=escape_sha,
        train_id=train_id,
        node_id=node_id,
        fab_run_id="run1",
        roadmap_digest=roadmap_digest,
        provenance_digest="p" * 64,
        owned_scope=("a.py",),
    )
    replay_before_escape = tuple(store.replay())
    receipt_before_escape = replay_before_escape[-1]
    with pytest.raises((PermissionError, ValueError), match=r"(?i)scope|unowned"):
        readmit_service.readmit_advanced_head(out_of_scope_auth)

    replay_after_escape = tuple(store.replay())
    assert len(replay_after_escape) == len(replay_before_escape)
    assert replay_after_escape == replay_before_escape
    assert replay_after_escape[-1] == receipt_before_escape
    assert len(readmit_adapter.calls) == 0
