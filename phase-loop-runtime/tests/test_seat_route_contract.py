from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from phase_loop_runtime import claude_seat_transport, seat_jail
from phase_loop_runtime import seat_route_contract as contract


EXPECTED_DESCEND_CODES = frozenset({
    "seat_sandbox_unavailable_host",
    "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "seat_egress_not_installed",
})
EXPECTED_SECURITY_CODES = frozenset({
    "claude_sdk_provenance_refused",
    "claude_sdk_worker_contract_violation",
    "claude_seat_api_key_source",
    "claude_seat_token_in_output",
    "gemini_seat_credential_unusable",
    "gemini_seat_egress_unconfined",
    "gemini_seat_stream_split_unavailable",
    "gemini_seat_subagent_or_unknown_event",
    "gemini_seat_token_in_output",
    "gemini_seat_token_refreshed_in_jail",
    "gemini_seat_token_scope_excess",
    "seat_egress_integrity_failed",
    "seat_egress_tls_unterminated",
    "seat_output_retained_after_teardown",
    "seat_route_identity_invalid",
    "seat_sandbox_egress_opt_out",
    "seat_sandbox_refused:identity",
    "seat_sandbox_refused:output_unsafe",
    "seat_sandbox_refused:stage_changed",
    "seat_sandbox_refused:stage_not_private",
    "seat_sandbox_refused:token_file_unsafe",
    "seat_sandbox_retained_after_teardown",
})


def test_closed_code_sets_are_literal_contract_values():
    assert contract.DESCEND_CODES == EXPECTED_DESCEND_CODES
    assert contract.REMOTE_DESCEND_CODES == frozenset()
    assert contract.CAPACITY_CODES == frozenset({"seat_local_capacity_exhausted"})
    assert frozenset(
        code for code, classification in contract.OD10_CLASSES.items()
        if classification == "security"
    ) == EXPECTED_SECURITY_CODES


def test_route_codes_are_complete_classified_and_name_no_retired_route():
    assert set(contract.CODES) <= set(contract.OD10_CLASSES)
    for code, (classification, what, why, fix) in contract.CODES.items():
        assert classification in {"security", "ordinary"}, code
        assert what.strip() and why.strip() and fix.strip(), code
        assert "sealed route" not in fix.lower(), code
        assert "inline route" not in fix.lower(), code
        assert "key-based" not in fix.lower(), code
    with pytest.raises(RuntimeError, match="synthetic"):
        contract._validate_contract(
            {"synthetic": ("ordinary", "what", "why", "fix")}, {}
        )


def test_every_current_mode_line_code_has_an_explicit_class():
    claude_route_codes = {
        "panel_claude_route_invalid", "panel_claude_transport_not_admitted",
    }
    current = (
        set(seat_jail.NOTICE_CODES) | set(claude_seat_transport.CODES)
        | set(contract.CODES) | claude_route_codes
    )
    assert set(contract.OD10_CLASSES) == current
    assert all(contract.OD10_CLASSES[code] == "ordinary" for code in claude_route_codes)
    assert all(value in {"security", "ordinary"} for value in contract.OD10_CLASSES.values())
    assert all(
        contract.OD10_CLASSES[code] == entry[0]
        for code, entry in claude_seat_transport.CODES.items()
    )


def test_qualification_digest_and_record_binding_cover_every_field():
    base = contract.QualificationKey(
        profile_digest="profile",
        allowlist_digest="allowlist",
        falsifier_layout="layout",
        projection_digest="projection",
        variant="tui",
        host_identity="host",
    )
    base_digest = contract.key_digest(base)
    assert dict(contract.record_binding(base)) == dataclasses.asdict(base)
    for field in dataclasses.fields(base):
        changed = dataclasses.replace(base, **{field.name: f"changed-{field.name}"})
        assert contract.key_digest(changed) != base_digest, field.name
        assert dict(contract.record_binding(changed)) != dict(contract.record_binding(base))


def test_route_policy_overlay_is_capacity_only_and_rejects_wildcards():
    with pytest.raises(ValueError, match="capacity_offload only"):
        contract.validate_route_policy({"capacity_offload": [], "routed_remote": []})
    raw = {
        "target": "owner-a",
        "target_class": "owner_controlled",
        "host_classes": ["standard"],
        "vendors": ["gemini"],
        "probe_set_digest": "probe",
        "probe_receipt": "receipt",
        "activation_refs": {},
    }
    grants = contract.validate_route_policy({"capacity_offload": [raw]})
    assert grants == (contract.CapacityGrant(
        target="owner-a",
        target_class="owner_controlled",
        host_classes=frozenset({"standard"}),
        vendors=frozenset({"gemini"}),
        probe_set_digest="probe",
        probe_receipt="receipt",
        activation_refs={},
    ),)
    with pytest.raises(ValueError, match="vendors"):
        contract.validate_route_policy({"capacity_offload": [{**raw, "vendors": ["*"]}]})
    with pytest.raises(ValueError, match="host_classes"):
        contract.validate_route_policy({"capacity_offload": [{**raw, "host_classes": ["*"]}]})
    with pytest.raises(ValueError, match="capacity_offload only"):
        contract.validate_route_policy(["capacity_offload"])


def test_contract_module_imports_no_io_or_runtime_module():
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the contract module uses a relative import"
            imported.add(node.module or "")
    assert imported <= {
        "__future__", "dataclasses", "datetime", "hashlib", "json", "types", "typing",
    }, sorted(imported)
