"""FABREADMIT (v10) broker admission-only tests — SL-0, immutable contract.
"""

from __future__ import annotations

import pytest

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


def _exec_behavioral_red_node(request, fn):
    valid = False
    try:
        fn()
        valid = True
    except Exception:
        valid = False
    fabreadmit_require(fabreadmit_this_nodeid(request), valid)


def test_fabreadmit_broker_authority_receipt_contract(request):
    """IF-0-FABREADMIT-1 authority and receipt shape contract."""
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    def _run_test():
        from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, DeltaReadmitReceipt
        from phase_loop_runtime.convergence.broker.live import BrokerClient

        # 1. Instantiate authority with canonical fields
        auth = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness",
            adapter_worktree="/tmp/wt",
            checkpoint_root="/tmp/ckpt",
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

        # Immutability: attribute assignment must be forbidden
        with pytest.raises((TypeError, AttributeError)):
            auth.branch = "other"  # type: ignore

        # Forbidden caller-supplied fields: constructor must reject caller-supplied epoch, attempt_id, etc.
        for forbidden in ("epoch", "attempt_id", "fence_token", "approval_digest", "idempotency_key"):
            with pytest.raises((TypeError, AttributeError, ValueError)):
                DeltaReadmitAuthority(**{"repository": "r", forbidden: "val"})

        # 2. Instantiate receipt and verify bound fields
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

        # 3. Client method presence
        assert hasattr(BrokerClient, "readmit_advanced_head")

    _exec_behavioral_red_node(request, _run_test)


def test_fabreadmit_broker_rediffs_head_range_and_rejects_scope_escape_without_adapter(request, tmp_path):
    """Broker independently re-diffs prior..proposed, rejects scope escape, calls zero adapters."""
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    def _run_test():
        from phase_loop_runtime.convergence.broker.verbs import BrokerService
        from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
        from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
        from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority

        adapter = _CountingAdapter()
        store = LinearizableAdmissionStore(tmp_path / "admissions", lambda _: True)
        evidence = BrokerEvidenceStore(tmp_path / "evidence")
        service = BrokerService(store, evidence, adapter)

        # 1. In-scope authority execution: zero adapter calls
        in_scope_auth = DeltaReadmitAuthority(
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

        receipt = service.readmit_advanced_head(in_scope_auth)
        assert receipt is not None
        assert adapter.calls == 0, "in-scope readmission must perform zero adapter calls"

        # 2. Scope-escape authority execution: zero adapter calls and denial
        out_of_scope_auth = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness",
            adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"),
            branch="feat/x",
            base="main",
            prior_head_sha="a" * 40,
            proposed_head_sha="c" * 40,
            train_id="train1",
            node_id="n1",
            fab_run_id="run1",
            roadmap_digest="d" * 64,
            provenance_digest="p" * 64,
            owned_scope=("pkg",),
        )
        with pytest.raises((PermissionError, ValueError)):
            service.readmit_advanced_head(out_of_scope_auth)

        assert adapter.calls == 0, "scope-escape denial must perform zero adapter calls"

    _exec_behavioral_red_node(request, _run_test)
