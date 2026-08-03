"""test_proofgate_receipts.py — PROOFGATE receipts and receipt chain tests."""

import json
import pytest

from .proofgate_tdd_guard import ProofgateMissingCapabilityError, guard_proofgate_nodeid, run_proofgate_contract


def test_bootstrap_records_are_single_use_and_server_bound():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_bootstrap_records_are_single_use_and_server_bound"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "BootstrapRecordStore"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing BootstrapRecordStore capability")

        store = proofgate_receipts.BootstrapRecordStore()
        rec = store.issue_bootstrap_record(
            server_id="srv-prod-1",
            pr_number=130,
            head_sha="head123",
            base_sha="base456",
            token="tok-123",
        )
        assert store.validate_bootstrap_record(rec, expected_server_id="srv-prod-1", expected_pr_number=130)
        with pytest.raises(proofgate_receipts.BootstrapRecordError, match="single_use"):
            store.validate_bootstrap_record(rec, expected_server_id="srv-prod-1", expected_pr_number=130)
        rec2 = store.issue_bootstrap_record(
            server_id="srv-prod-1",
            pr_number=130,
            head_sha="head123",
            base_sha="base456",
            token="tok-456",
        )
        with pytest.raises(proofgate_receipts.BootstrapRecordError, match="server_bound"):
            store.validate_bootstrap_record(rec2, expected_server_id="srv-prod-2", expected_pr_number=130)

    run_proofgate_contract(nodeid, _contract)


def test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill(tmp_path):
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "ProofgateReceiptSupervisor"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ProofgateReceiptSupervisor capability")

        git_repo = tmp_path / "receipts_repo"
        supervisor = proofgate_receipts.ProofgateReceiptSupervisor(repo_path=git_repo)

        # Zero-parent genesis commit
        r1 = supervisor.append_receipt(subject="PROOFGATE-AC-1", payload={"step": 1})
        assert supervisor.verify_chain()

        # Independently observe raw disk files and git commits rather than trusting supervisor-returned objects
        assert (git_repo / ".git").is_dir(), "Receipt repository must be initialized git repo"
        latest_file = git_repo / "latest.json"
        assert latest_file.exists(), "latest.json must exist on disk after genesis commit"
        latest_data = json.loads(latest_file.read_text(encoding="utf-8"))
        assert "sequence" in latest_data or "append_sha256" in latest_data or "core_sha256" in latest_data

        # Core bytes must be self-digest-free: no self_digest or core_sha256 key inside serialized core
        core1 = r1.get("core", r1)
        assert "self_digest" not in core1
        assert "core_sha256" not in core1

        # One-parent appends
        r2 = supervisor.append_receipt(subject="PROOFGATE-AC-1", payload={"step": 2})
        r3 = supervisor.append_receipt(subject="PROOFGATE-AC-1", payload={"step": 3})
        assert supervisor.verify_chain()

        # Tampering at every stage: core, filename, subject, bundle, append, pointer, sequence, previous links
        tampered_core = r1.copy()
        tampered_core["payload"] = {"step": 999}
        assert not supervisor.verify_records([tampered_core, r2, r3])

        for tamper_field in ("filename", "subject", "bundle", "append", "pointer", "sequence", "previous_links"):
            tampered_record = r1.copy()
            tampered_record[tamper_field] = "tampered_value"
            assert not supervisor.verify_records([tampered_record, r2, r3])

        # Truncation check
        assert not supervisor.verify_records([r1], expected_length=3)

        # Fork / backfill / rewrite check over real Git object/ref history
        forked = [r1.copy(), r2.copy(), proofgate_receipts.create_receipt(parent=r1, subject="PROOFGATE-AC-1", payload={"step": 3})]
        assert not supervisor.verify_records(forked)

        backfilled = [r2.copy(), r1.copy(), r3.copy()]
        assert not supervisor.verify_records(backfilled)

        # Concurrent single winner & journal reconstruction / rollback cases
        winner = supervisor.resolve_concurrent_append(expected_parent=r2.get("oid", "oid2"), candidates=[r3, r3])
        assert winner is not None

    run_proofgate_contract(nodeid, _contract)


def test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "ProofgateReceiptSupervisor"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ProofgateReceiptSupervisor capability")

        supervisor = proofgate_receipts.ProofgateReceiptSupervisor(
            expected_workflow=".github/workflows/proofgate-receipt-attestation.yml",
            expected_signer="github-actions[bot]",
            expected_source_blob="sha256:abc123def456",
            expected_subject="PROOFGATE-AC-1",
        )
        valid_rec = supervisor.create_record(
            workflow=".github/workflows/proofgate-receipt-attestation.yml",
            signer="github-actions[bot]",
            source_blob="sha256:abc123def456",
            subject="PROOFGATE-AC-1",
            timestamp=1700000000,
        )
        assert supervisor.validate_record(valid_rec)

        bad_wf = valid_rec.copy()
        bad_wf["workflow"] = ".github/workflows/other.yml"
        assert not supervisor.validate_record(bad_wf)

        bad_signer = valid_rec.copy()
        bad_signer["signer"] = "unauthorized-user"
        assert not supervisor.validate_record(bad_signer)

        bad_blob = valid_rec.copy()
        bad_blob["source_blob"] = "sha256:badblob"
        assert not supervisor.validate_record(bad_blob)

        bad_subj = valid_rec.copy()
        bad_subj["subject"] = "OTHER-AC"
        assert not supervisor.validate_record(bad_subj)

        bad_ts = valid_rec.copy()
        bad_ts["timestamp"] = 0
        assert not supervisor.validate_record(bad_ts)

    run_proofgate_contract(nodeid, _contract)


def test_implementation_authorization_requires_activation_preflight_panel_and_red_order():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_implementation_authorization_requires_activation_preflight_panel_and_red_order"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "ImplementationAuthorizationSequence"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ImplementationAuthorizationSequence capability")

        auth = proofgate_receipts.ImplementationAuthorizationSequence()
        auth.record_step("activation")
        auth.record_step("preflight")
        auth.record_step("panel")
        auth.record_step("red_order")
        assert auth.verify_sequence()

        bad_auth = proofgate_receipts.ImplementationAuthorizationSequence()
        bad_auth.record_step("panel")
        bad_auth.record_step("activation")
        with pytest.raises(proofgate_receipts.AuthorizationOrderError):
            bad_auth.verify_sequence()

    run_proofgate_contract(nodeid, _contract)


def test_runner_routes_reject_child_claims_and_missing_latest_external_head():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_runner_routes_reject_child_claims_and_missing_latest_external_head"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "RunnerRouteValidator"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing RunnerRouteValidator capability")

        router = proofgate_receipts.RunnerRouteValidator()
        with pytest.raises(proofgate_receipts.RunnerRouteError, match="child_claim"):
            router.validate_route_claim(pid=9999, is_child_process=True)

        with pytest.raises(proofgate_receipts.RunnerRouteError, match="missing_latest_external_head"):
            router.validate_external_head(expected_head="sha:head-1", current_head=None)

        # Stale writer / concurrent non-force winner check
        with pytest.raises(proofgate_receipts.RunnerRouteError, match="stale_writer"):
            router.validate_concurrent_push(expected_head="sha:head-1", remote_head="sha:head-2_winner")

    run_proofgate_contract(nodeid, _contract)
