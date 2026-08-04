"""test_proofgate_attestation_workflow.py — GitHub Actions attestation workflow tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from .proofgate_tdd_guard import guard_proofgate_nodeid, run_proofgate_contract


class UnitAttestationServiceDouble:
    """Explicit non-decisive unit-double attestation service for tests."""

    def verify_attestation(self, attestation_data: dict) -> dict:
        if not isinstance(attestation_data, dict):
            raise ValueError("attestation_data must be a dictionary")
        if not attestation_data.get("github_hosted"):
            raise ValueError("github_hosted_required")

        subject = attestation_data.get("subject", "")
        source_blob_sha256 = attestation_data.get("source_blob_sha256", "")

        if not subject or not subject.startswith("cores/") or not subject.endswith(".json"):
            raise ValueError("subject_mismatch")

        # Subject filename format: cores/<20-digit-sequence>-<core_sha256>.json
        fname = subject.split("/")[-1]
        parts = fname.replace(".json", "").split("-")
        if len(parts) != 2 or len(parts[0]) != 20 or len(parts[1]) != 64:
            raise ValueError("subject_mismatch")

        subj_sha256 = parts[1]
        if source_blob_sha256 and subj_sha256 != source_blob_sha256:
            raise ValueError("source_blob_mismatch")

        # Core bytes (if provided) must NOT contain self-digest key or value
        core_bytes = attestation_data.get("core_bytes")
        if core_bytes is not None:
            try:
                core_obj = json.loads(core_bytes.decode("utf-8") if isinstance(core_bytes, bytes) else core_bytes)
                if isinstance(core_obj, dict):
                    if "core_sha256" in core_obj:
                        raise ValueError("self_digest_forbidden: core contains core_sha256 key")
                    for val in core_obj.values():
                        if str(val) == subj_sha256:
                            raise ValueError("self_digest_forbidden: core value equals core_sha256")
            except json.JSONDecodeError:
                pass

        return {
            "status": "verified",
            "evidence_kind": "unit_double",
            "decisive": False,
            "subject": subject,
            "source_blob_sha256": source_blob_sha256,
        }


def test_attestation_workflow_is_github_hosted_exact_subject_and_blob_bound():
    nodeid = "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py::test_attestation_workflow_is_github_hosted_exact_subject_and_blob_bound"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from .proofgate_bootstrap_verifier import (
            ProofgateContractViolation,
            assert_external_attestation_contract,
            verify_external_observation,
        )
        from .proofgate_tdd_guard import (
            PROOFGATE_EXPECTED_CONFIG_V1,
            ProofgateMissingCapabilityError,
            assert_frozen_authority_contract,
        )

        # Control A: the typed authority contracts are frozen and authority-free.
        assert_frozen_authority_contract()

        # Control B: the oracle is not vacuous — the test-owned reference verifier satisfies it.
        assert_external_attestation_contract(verify_external_observation, expected=PROOFGATE_EXPECTED_CONFIG_V1)

        # Control C: an attestation service whose external method accepts a caller-created mapping
        # and returns a renamed decisive evidence-kind label must reject.
        class _RenamedLabelAttestationService:
            def verify_external_attestation(self, attestation_data, **kwargs):
                if isinstance(attestation_data, dict):
                    return {"status": "verified", "evidence_kind": "production_attestation", "decisive": True}
                boundary = kwargs.get("boundary")
                if boundary is not None:
                    boundary.observe(attestation_data)
                return {"status": "verified", "evidence_kind": "production_attestation", "decisive": True}

        with pytest.raises(ProofgateContractViolation):
            assert_external_attestation_contract(
                _RenamedLabelAttestationService().verify_external_attestation,
                expected=PROOFGATE_EXPECTED_CONFIG_V1,
            )

        # Control D: a sound locator path cannot redeem a caller-mapping path that reports
        # verified/decisive authority under a renamed evidence kind.
        class _DualSurfaceAttestationService:
            def verify_external_attestation(self, attestation_data, **kwargs):
                if isinstance(attestation_data, dict):
                    return {
                        "status": "verified",
                        "decisive": True,
                        "evidence_kind": "production_attestation",
                    }
                return verify_external_observation(
                    attestation_data,
                    expected=kwargs["expected"],
                    boundary=kwargs["boundary"],
                )

        with pytest.raises(ProofgateContractViolation):
            assert_external_attestation_contract(
                _DualSurfaceAttestationService().verify_external_attestation,
                expected=PROOFGATE_EXPECTED_CONFIG_V1,
            )

        try:
            from phase_loop_runtime import proofgate_receipts
            if not hasattr(proofgate_receipts, "ProofgateAttestationService") and not hasattr(proofgate_receipts, "ProofgateReceiptSupervisor"):
                raise ProofgateMissingCapabilityError("proofgate_receipts missing ProofgateAttestationService capability")
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        workflow_path = Path(__file__).resolve().parents[2] / ".github/workflows/proofgate-receipt-attestation.yml"
        assert workflow_path.exists(), "Attestation workflow file missing: .github/workflows/proofgate-receipt-attestation.yml"

        if not hasattr(proofgate_receipts, "ProofgateAttestationService"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ProofgateAttestationService capability")

        verifier = proofgate_receipts.ProofgateAttestationService()
        double_ctrl = UnitAttestationServiceDouble()

        # Step 1: Create canonical core bytes without self-digest
        core_obj = {
            "schema": "proofgate_attested_core.v1",
            "sequence": 1,
            "repository": "Consiliency/agent-harness",
            "workflow_path": ".github/workflows/proofgate-receipt-attestation.yml",
            "environment": "proofgate-receipt-head-v1",
            "previous_core_digest": None,
            "expected_previous_external_head_oid": None,
        }
        core_bytes = json.dumps(core_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        core_sha256 = hashlib.sha256(core_bytes).hexdigest()

        seq_str = f"{1:020d}"
        subject_name = f"cores/{seq_str}-{core_sha256}.json"

        valid_attestation = {
            "github_hosted": True,
            "runner_environment": "github-hosted",
            "subject": subject_name,
            "source_blob_sha256": core_sha256,
            "core_bytes": core_bytes,
        }
        ctrl_res = double_ctrl.verify_attestation(valid_attestation)
        assert ctrl_res["evidence_kind"] == "unit_double"
        assert ctrl_res["decisive"] is False

        res = verifier.verify_attestation(valid_attestation)
        assert res["status"] == "verified"
        assert res["evidence_kind"] == "unit_double"
        assert res["decisive"] is False

        # Step 2: the production positive obtains decisive status ONLY from the read-only external
        # observation boundary. The caller passes no attestation mapping and no evidence bytes,
        # status, decisive flag, hashes or identities — only the locator, the immutable expected
        # configuration and a recording boundary whose exact call trace is asserted.
        if not hasattr(verifier, "verify_external_attestation"):
            raise ProofgateMissingCapabilityError(
                "ProofgateAttestationService missing verify_external_attestation capability"
            )

        assert_external_attestation_contract(
            verifier.verify_external_attestation,
            expected=PROOFGATE_EXPECTED_CONFIG_V1,
        )

        # Unit doubles and production objects returning evidence_kind=unit_double MUST remain non-decisive
        assert ctrl_res["decisive"] is False
        assert res["decisive"] is False

        # Tamper 1: Not github hosted must fail
        bad_host = valid_attestation.copy()
        bad_host["github_hosted"] = False
        with pytest.raises(ValueError, match="github_hosted_required"):
            verifier.verify_attestation(bad_host)

        # Tamper 2: Malformed subject must fail
        bad_subj = valid_attestation.copy()
        bad_subj["subject"] = "OTHER-AC"
        with pytest.raises(ValueError, match="subject_mismatch"):
            verifier.verify_attestation(bad_subj)

        # Tamper 3: Source blob digest mismatch must fail
        bad_blob = valid_attestation.copy()
        bad_blob["source_blob_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="source_blob_mismatch"):
            verifier.verify_attestation(bad_blob)

        # Tamper 4: Core containing self-digest key must fail
        self_digest_core = dict(core_obj)
        self_digest_core["core_sha256"] = core_sha256
        self_digest_bytes = json.dumps(self_digest_core, sort_keys=True, separators=(",", ":")).encode("utf-8")
        bad_self_dig = valid_attestation.copy()
        bad_self_dig["core_bytes"] = self_digest_bytes
        with pytest.raises(ValueError, match="self_digest_forbidden"):
            verifier.verify_attestation(bad_self_dig)

    run_proofgate_contract(nodeid, _contract)
