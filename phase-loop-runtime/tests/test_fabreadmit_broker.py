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
    _check_guard_inventory()


from _fabreadmit_tdd_guard import (
    FABREADMIT_SKIP_REASON,
    fabreadmit_capability_active,
    fabreadmit_require,
    fabreadmit_symbol,
    fabreadmit_this_nodeid,
)


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
    from phase_loop_runtime.convergence.broker.admission import (
        LinearizableAdmissionStore,
        LegacyBrokerCutoverManifest,
        run_legacy_broker_cutover,
    )
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
    from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority

    # 1. Setup real Git repository with committed range
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test"], check=True)
    (repo_dir / "pkg").mkdir()
    (repo_dir / "pkg" / "a.py").write_text("v1\n", encoding="utf-8")
    (repo_dir / "unowned.py").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "init"], check=True)
    base_sha = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    # Commit 1 (in scope): touches pkg/a.py
    (repo_dir / "pkg" / "a.py").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "in scope"], check=True)
    in_scope_sha = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    # Commit 2 (scope escape): touches unowned.py
    (repo_dir / "unowned.py").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "escape"], check=True)
    escape_sha = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    # 2. Setup activated store partition (FR-SL0-04)
    cutover_dir = tmp_path / "cutover"
    cutover_dir.mkdir(parents=True, exist_ok=True)
    manifest = LegacyBrokerCutoverManifest(
        repository="Consiliency/agent-harness",
        prior_head_sha=base_sha,
        checkpoint_root=str(tmp_path / "ckpt"),
    )
    receipt = run_legacy_broker_cutover(manifest, cutover_dir)
    receipt.activate()

    partition_dir = tmp_path / "partition"
    partition_dir.mkdir(parents=True, exist_ok=True)
    adapter = _CountingAdapter()
    store = LinearizableAdmissionStore(partition_dir, lambda _: True)
    evidence = BrokerEvidenceStore(partition_dir)
    service = BrokerService(store, evidence, adapter)

    # In-scope execution
    in_scope_auth = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness",
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(tmp_path / "ckpt"),
        branch="feat/x",
        base="main",
        prior_head_sha=base_sha,
        proposed_head_sha=in_scope_sha,
        train_id="train1",
        node_id="n1",
        fab_run_id="run1",
        roadmap_digest="d" * 64,
        provenance_digest="p" * 64,
        owned_scope=("pkg/",),
    )
    res_in = service.readmit_advanced_head(in_scope_auth)
    assert res_in is not None
    assert adapter.calls == 0

    # Scope-escape execution
    out_of_scope_auth = DeltaReadmitAuthority(
        repository="Consiliency/agent-harness",
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(tmp_path / "ckpt"),
        branch="feat/x",
        base="main",
        prior_head_sha=in_scope_sha,
        proposed_head_sha=escape_sha,
        train_id="train1",
        node_id="n1",
        fab_run_id="run1",
        roadmap_digest="d" * 64,
        provenance_digest="p" * 64,
        owned_scope=("pkg/",),
    )
    with pytest.raises((PermissionError, ValueError), match=r"(?i)scope|unowned"):
        service.readmit_advanced_head(out_of_scope_auth)

    assert adapter.calls == 0
