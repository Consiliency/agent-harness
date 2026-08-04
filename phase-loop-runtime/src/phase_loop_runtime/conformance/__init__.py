"""``phase_loop_runtime.conformance`` -- the named conformance surface.

This package preserves the existing public ``.consiliency/`` conformance
imports while providing a namespace for outside-agent contract pin helpers.

TIERS.
    * SHAPE / GOVERNANCE tier -- :func:`scan_consiliency_gates` and its pure
      cores: the deterministic, consent-gated evaluator over a repo's
      ``.consiliency/`` layout.
    * CERT / SCHEMA tier -- :func:`validate_certificate`: structural conformance
      of a DECLARED parity certificate to the contract-distributed
      ``certificate`` schema (contract 0.6.4+). Loaded via the same
      ``consiliency_contract`` loader the SHAPE gates use; versioned with the
      contract; degrades to a neutral ``skipped`` verdict when the schema is
      absent. It is NOT authority / provenance / signing -- that stays gp.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "scan_consiliency_gates",
    "resolve_consiliency_gates_mode",
    "CONSILIENCY_GATES_ENV",
    "CONSILIENCY_GATES_MODES",
    "DEFAULT_CONSILIENCY_GATES_MODE",
    "evaluate_git_discipline",
    "self_heal_partition",
    "evaluate_governance_scope",
    "validate_certificate",
    "certificate_schema_available",
    "GIT_GROUNDED_KIND",
    "GIT_GROUNDED_PROJECTION_SCHEMA",
    "PORTAL_KIND_MISNOMER",
    "RAW_SHA256_DOMAIN",
    "GitGroundedContractAbsent",
    "GitGroundedProjection",
    "build_git_grounded_body",
    "build_projection_index_entry",
    "reconcile_git_grounded_projection",
    "OutsideAgentBlocker",
    "OutsideAgentConformanceVerdict",
    "OutsideAgentEvidenceRef",
    "OutsideAgentSubmissionKind",
    "OutsideAgentVerdictStatus",
    "validate_outside_agent_submission",
    "OutsideAgentAdvisoryEvidence",
    "OutsideAgentAdvisoryExitCode",
    "build_outside_agent_advisory_evidence",
    "serialize_outside_agent_advisory_evidence",
    "OutsideAgentContractError",
    "load_outside_agent_contract_pin",
    "EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN",
    "OutsideAgentContractPin",
    "OutsideAgentSubmittedRef",
    "OutsideAgentValidationExitCode",
    "OutsideAgentValidationVerdict",
    "build_outside_agent_validation_verdict",
    "digest_outside_agent_validation_bytes",
    "serialize_outside_agent_validation_verdict",
]

_EXPORT_MODULES = {
    "scan_consiliency_gates": "phase_loop_runtime.consiliency_gates",
    "resolve_consiliency_gates_mode": "phase_loop_runtime.consiliency_gates",
    "CONSILIENCY_GATES_ENV": "phase_loop_runtime.consiliency_gates",
    "CONSILIENCY_GATES_MODES": "phase_loop_runtime.consiliency_gates",
    "DEFAULT_CONSILIENCY_GATES_MODE": "phase_loop_runtime.consiliency_gates",
    "evaluate_git_discipline": "phase_loop_runtime.git_discipline",
    "self_heal_partition": "phase_loop_runtime.git_discipline",
    "evaluate_governance_scope": "phase_loop_runtime.consiliency_ingest",
    "validate_certificate": ".certificate_tier",
    "certificate_schema_available": ".certificate_tier",
    "GIT_GROUNDED_KIND": ".git_grounded_projection",
    "GIT_GROUNDED_PROJECTION_SCHEMA": ".git_grounded_projection",
    "PORTAL_KIND_MISNOMER": ".git_grounded_projection",
    "RAW_SHA256_DOMAIN": ".git_grounded_projection",
    "GitGroundedContractAbsent": ".git_grounded_projection",
    "GitGroundedProjection": ".git_grounded_projection",
    "build_git_grounded_body": ".git_grounded_projection",
    "build_projection_index_entry": ".git_grounded_projection",
    "reconcile_git_grounded_projection": ".git_grounded_projection",
    "OutsideAgentBlocker": ".outside_agent_core",
    "OutsideAgentConformanceVerdict": ".outside_agent_core",
    "OutsideAgentEvidenceRef": ".outside_agent_core",
    "OutsideAgentSubmissionKind": ".outside_agent_core",
    "OutsideAgentVerdictStatus": ".outside_agent_core",
    "validate_outside_agent_submission": ".outside_agent_core",
    "OutsideAgentAdvisoryEvidence": ".outside_agent_advisory",
    "OutsideAgentAdvisoryExitCode": ".outside_agent_advisory",
    "build_outside_agent_advisory_evidence": ".outside_agent_advisory",
    "serialize_outside_agent_advisory_evidence": ".outside_agent_advisory",
    "OutsideAgentContractError": ".outside_agent_imports",
    "load_outside_agent_contract_pin": ".outside_agent_imports",
    "EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN": ".outside_agent_pin",
    "OutsideAgentContractPin": ".outside_agent_pin",
    "OutsideAgentSubmittedRef": ".outside_agent_real",
    "OutsideAgentValidationExitCode": ".outside_agent_real",
    "OutsideAgentValidationVerdict": ".outside_agent_real",
    "build_outside_agent_validation_verdict": ".outside_agent_real",
    "digest_outside_agent_validation_bytes": ".outside_agent_real_output",
    "serialize_outside_agent_validation_verdict": ".outside_agent_real_output",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
