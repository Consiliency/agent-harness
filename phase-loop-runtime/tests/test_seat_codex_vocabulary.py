"""SEATS CODEX SL-0 (agent-harness#1820): the jailed Codex seat's code vocabulary.

IF-0-CODEX-5 adds nine ``codex_seat_*`` codes to ``seat_jail.NOTICES``, each with one
additive ``seat_route_contract.OD10_CLASSES`` entry. No existing entry changes, and neither
do the descend and capacity sets. The route itself does not change in this lane.
"""

from __future__ import annotations

import importlib

import pytest

from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_route_contract as contract


# The IF-0-CODEX-5 table: code -> OD-10 class.
CODEX_CODES: dict[str, str] = {
    "codex_seat_credential_missing": "ordinary",
    "codex_seat_api_key_refused": "ordinary",
    "codex_seat_token_expiring": "ordinary",
    "codex_seat_token_scope_excess": "security",
    "codex_seat_token_in_output": "security",
    "codex_seat_token_refreshed_in_jail": "security",
    "codex_seat_cli_shape": "ordinary",
    "codex_seat_tools_unavailable": "ordinary",
    "codex_seat_unknown_event": "security",
}

# The pre-CODEX literal values of the closed sets (contract §3); this lane changes none.
BASE_DESCEND_CODES = frozenset({
    "seat_sandbox_unavailable_host",
    "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "seat_egress_not_installed",
})
BASE_REMOTE_DESCEND_CODES: frozenset[str] = frozenset()
BASE_CAPACITY_CODES = frozenset({"seat_local_capacity_exhausted"})

# `seat_route_contract.OD10_CLASSES` at base 75ab6d17, before SEATS CODEX: a literal, never
# derived from the production tables, so a removed or renamed entry fails.
BASE_OD10_CLASSES: dict[str, str] = {
    "agy_image_unqualified": "ordinary",
    "claude_agent_view_review_unsupported": "ordinary",
    "claude_sdk_dependency_unavailable": "ordinary",
    "claude_sdk_provenance_refused": "security",
    "claude_sdk_worker_contract_violation": "security",
    "claude_sdk_worker_unavailable": "ordinary",
    "claude_seat_api_key_source": "security",
    "claude_seat_bypass_ack_blocked": "ordinary",
    "claude_seat_delivery_refused": "ordinary",
    "claude_seat_login_rate_limited": "ordinary",
    "claude_seat_login_rejected": "ordinary",
    "claude_seat_login_token_awaiting_refresh": "ordinary",
    "claude_seat_login_token_expired": "ordinary",
    "claude_seat_login_token_expiring": "ordinary",
    "claude_seat_login_unproven": "ordinary",
    "claude_seat_override_other_subscription": "ordinary",
    "claude_seat_result_unproven": "ordinary",
    "claude_seat_stream_unsafe": "ordinary",
    "claude_seat_token_in_output": "security",
    "claude_seat_token_missing": "ordinary",
    "claude_seat_token_rate_limited": "ordinary",
    "claude_seat_token_rejected": "ordinary",
    "claude_tui_journal_collection_refused": "ordinary",
    "claude_tui_workspace_trust_blocked": "ordinary",
    "executor_review_route_unsupported": "ordinary",
    "gemini_credential_awaiting_refresh": "ordinary",
    "gemini_credential_near_expiry": "ordinary",
    "gemini_credential_refresh_timeout": "ordinary",
    "gemini_seat_credential_missing": "ordinary",
    "gemini_seat_credential_unusable": "security",
    "gemini_seat_egress_unavailable": "ordinary",
    "gemini_seat_egress_unconfined": "security",
    "gemini_seat_profile_unqualified": "ordinary",
    "gemini_seat_qualification_candidate": "ordinary",
    "gemini_seat_stream_split_unavailable": "security",
    "gemini_seat_subagent_or_unknown_event": "security",
    "gemini_seat_token_expired": "ordinary",
    "gemini_seat_token_in_output": "security",
    "gemini_seat_token_refreshed_in_jail": "security",
    "gemini_seat_token_scope_excess": "security",
    "grok_tool_surface_unverified": "ordinary",
    "leg_auth_signed_out": "ordinary",
    "leg_auth_unavailable": "ordinary",
    "leg_exec_record_unavailable": "ordinary",
    "leg_execution_failed": "ordinary",
    "native_seat_unavailable_heartbeat_only": "ordinary",
    "panel_claude_route_invalid": "ordinary",
    "panel_claude_transport_not_admitted": "ordinary",
    "sandbox_placement_at_capacity": "ordinary",
    "sandbox_placement_backend_unregistered": "ordinary",
    "sandbox_placement_budget_spent": "ordinary",
    "sandbox_placement_capability_undeclared": "ordinary",
    "sandbox_placement_capability_unmet": "ordinary",
    "sandbox_placement_capacity_exhausted": "ordinary",
    "sandbox_placement_code_invalid": "ordinary",
    "sandbox_placement_driver_unavailable": "ordinary",
    "sandbox_placement_end_reached": "ordinary",
    "sandbox_placement_identity_mismatch": "ordinary",
    "sandbox_placement_local_release_unconfirmed": "ordinary",
    "sandbox_placement_lost_after_launch": "ordinary",
    "sandbox_placement_not_enrolled": "ordinary",
    "sandbox_placement_operation_timeout": "ordinary",
    "sandbox_placement_plugin_unavailable": "ordinary",
    "sandbox_placement_ref_invalid": "ordinary",
    "sandbox_placement_refused": "ordinary",
    "sandbox_placement_release_unconfirmed": "ordinary",
    "sandbox_placement_required_unavailable": "ordinary",
    "sandbox_placement_unreachable": "ordinary",
    "sandbox_placement_workload_unsupported": "ordinary",
    "seat_bind_source_unavailable": "ordinary",
    "seat_broker_socket_unavailable": "ordinary",
    "seat_capacity_offloaded": "ordinary",
    "seat_cli_adapter_missing": "ordinary",
    "seat_cli_platform_unsupported": "ordinary",
    "seat_cli_qualification_failed": "ordinary",
    "seat_cli_qualification_store_unsafe": "ordinary",
    "seat_cli_qualification_unavailable": "ordinary",
    "seat_cli_unqualified": "ordinary",
    "seat_egress_allowlist_missing": "ordinary",
    "seat_egress_integrity_failed": "security",
    "seat_egress_not_installed": "ordinary",
    "seat_egress_start_failed": "ordinary",
    "seat_egress_tls_unterminated": "security",
    "seat_filesystem_unconfined": "ordinary",
    "seat_filtered_egress_unavailable": "ordinary",
    "seat_identity_unverified": "ordinary",
    "seat_jail_qualification_failed": "ordinary",
    "seat_keyring_unavailable": "ordinary",
    "seat_launch_owner_required": "ordinary",
    "seat_local_capacity_exhausted": "ordinary",
    "seat_native_fill_unavailable": "ordinary",
    "seat_output_inside_readonly_input": "ordinary",
    "seat_output_path_unavailable": "ordinary",
    "seat_output_retained_after_teardown": "security",
    "seat_owner_unavailable": "ordinary",
    "seat_placement_waiting": "ordinary",
    "seat_profile_unavailable": "ordinary",
    "seat_profile_unregistered": "ordinary",
    "seat_prompt_over_cap": "ordinary",
    "seat_provider_unavailable": "ordinary",
    "seat_remote_rung_inactive": "ordinary",
    "seat_resource_caps_unavailable": "ordinary",
    "seat_route_exception_expired": "ordinary",
    "seat_route_identity_invalid": "security",
    "seat_route_policy_ignored": "ordinary",
    "seat_route_row_remote": "ordinary",
    "seat_sandbox_egress_opt_out": "security",
    "seat_sandbox_not_staged": "ordinary",
    "seat_sandbox_refused:gemini_credential_unsafe": "ordinary",
    "seat_sandbox_refused:identity": "security",
    "seat_sandbox_refused:jail_build": "ordinary",
    "seat_sandbox_refused:jail_unqualified": "ordinary",
    "seat_sandbox_refused:namespace": "ordinary",
    "seat_sandbox_refused:output_unsafe": "security",
    "seat_sandbox_refused:pass_store_unsafe": "ordinary",
    "seat_sandbox_refused:preseed": "ordinary",
    "seat_sandbox_refused:stage_changed": "security",
    "seat_sandbox_refused:stage_not_private": "security",
    "seat_sandbox_refused:token_file_unsafe": "security",
    "seat_sandbox_retained_after_teardown": "security",
    "seat_sandbox_root_fell_back": "ordinary",
    "seat_sandbox_root_unapplied": "ordinary",
    "seat_sandbox_unavailable_host": "ordinary",
    "seat_sandbox_unavailable_seat_uid": "ordinary",
    "seat_sandbox_unavailable_tiocsti": "ordinary",
    "seat_staging_below_floor": "ordinary",
    "seat_tool_denied": "ordinary",
    "seat_tool_sandbox_unavailable": "ordinary",
    "under_claude_code": "ordinary",
}

# Fix-line phrases that would name a retired route or a key-based credential.
RETIRED_ROUTE_WORDS = ("sealed", "inline", "key-based", "api key", "api-key", "apikey")


def test_the_table_has_nine_codex_codes_and_no_others():
    assert len(CODEX_CODES) == 9
    assert seat_jail.CODEX_SEAT_CODES == frozenset(CODEX_CODES)
    published = {code for code in seat_jail.NOTICES if code.startswith("codex_seat_")}
    assert published == set(CODEX_CODES)
    classified = {code for code in contract.OD10_CLASSES if code.startswith("codex_seat_")}
    assert classified == set(CODEX_CODES)


@pytest.mark.parametrize("code", sorted(CODEX_CODES))
def test_each_code_is_an_exact_detail_literal(code):
    """Contract §4: the closed detail vocabulary includes every notice code, so a leg
    detail carrying one finalizes to the code itself, never the unknown-failure template."""
    from phase_loop_runtime import panel_invoker as pi

    assert code in pi._HARNESS_DETAIL_CODES
    assert pi._finalize_leg_detail(code) == code


@pytest.mark.parametrize("code", sorted(CODEX_CODES))
def test_each_code_has_a_complete_notice_row(code):
    what, why, fix = seat_jail.NOTICES[code]
    assert what.strip() and why.strip() and fix.strip()
    notice = seat_jail.render_notice(code, "codex:a")
    assert notice is not None
    assert (notice.code, notice.what, notice.why, notice.fix) == (code, what, why, fix)
    assert seat_jail.SeatSandboxRefused(code).code == code


@pytest.mark.parametrize("code", sorted(CODEX_CODES))
def test_each_code_has_one_od10_entry_with_the_table_class(code):
    expected = CODEX_CODES[code]
    assert contract.OD10_CLASSES[code] == expected
    in_security = code in contract._SECURITY_CODES
    in_ordinary = code in contract._ORDINARY_CODES
    assert (in_security, in_ordinary) == (expected == "security", expected == "ordinary")


@pytest.mark.parametrize("code", sorted(CODEX_CODES))
def test_no_fix_line_names_a_sealed_inline_or_key_route(code):
    fix = seat_jail.NOTICES[code][2].lower()
    for word in RETIRED_ROUTE_WORDS:
        assert word not in fix, (code, word)


def test_security_codes_ask_for_a_private_report():
    for code, cls in CODEX_CODES.items():
        if cls == "security":
            assert "report the outcome privately" in seat_jail.NOTICES[code][2], code


@pytest.mark.parametrize("code", sorted(CODEX_CODES))
def test_every_codex_code_is_terminal(code):
    assert code not in contract.DESCEND_CODES
    assert code not in contract.REMOTE_DESCEND_CODES
    assert code not in contract.CAPACITY_CODES
    assert code not in seat_jail.SEALED_FALLBACK_CODES
    assert code not in seat_jail.JAIL_NOT_RUN_CODES


def test_descend_and_capacity_sets_keep_their_literal_values():
    assert contract.DESCEND_CODES == BASE_DESCEND_CODES
    assert contract.REMOTE_DESCEND_CODES == BASE_REMOTE_DESCEND_CODES
    assert contract.CAPACITY_CODES == BASE_CAPACITY_CODES


def test_removing_the_codex_entries_leaves_the_base_table():
    """Without the nine codes, OD-10 classifies exactly the rest of the mode line closure,
    and the codex entries are the only additions to the table."""
    from phase_loop_runtime import claude_seat_transport

    base = {code: cls for code, cls in contract.OD10_CLASSES.items()
            if not code.startswith("codex_seat_")}
    assert len(BASE_OD10_CLASSES) == 129
    assert base == BASE_OD10_CLASSES
    base_closure = (
        (set(seat_jail.NOTICE_CODES) - set(CODEX_CODES)) | set(claude_seat_transport.CODES)
        | set(contract.CODES) | {"panel_claude_route_invalid", "panel_claude_transport_not_admitted"}
    )
    assert set(base) == base_closure
    assert set(contract.OD10_CLASSES) - set(base) == set(CODEX_CODES)
    assert not contract._SECURITY_CODES & contract._ORDINARY_CODES
    contract._validate_contract()


def test_the_seat_route_import_closure_passes():
    """``seat_route`` refuses to import when its closure and OD-10 disagree."""
    seat_route = importlib.import_module("phase_loop_runtime.seat_route")
    closure = seat_route.mode_line_codes()
    assert set(CODEX_CODES) <= closure
    assert closure == frozenset(contract.OD10_CLASSES)


def test_an_unsafe_auth_file_reuses_the_token_file_refusal():
    code = seat_jail.refused("token_file_unsafe")
    assert code == "seat_sandbox_refused:token_file_unsafe"
    assert not code.startswith("codex_seat_")
    assert contract.OD10_CLASSES[code] == "security"
