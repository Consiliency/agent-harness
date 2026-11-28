"""Shared core leg-detail and notice vocabulary (agent-harness#1501).

This leaf module holds the runtime's closed leg-detail literals so both
``panel_invoker`` (detail validation) and ``sandbox_placement.register_backend``
(collision rejection) read one vocabulary without ``leg_detail_vocabulary`` or
``sandbox_placement.register_backend`` importing ``panel_invoker``.
"""

from __future__ import annotations

from . import seat_jail as _seat_jail
from . import seat_route_contract as _seat_route_contract

HARNESS_DETAIL_CODES: frozenset[str] = frozenset({
    "sandbox_source_partial_clone",
    _seat_jail.REVIEW_BUNDLE_TOO_LARGE,
    # K-1 §9.1: a row window's typed refusals, which end a seat before anything starts.
    "window_unbudgeted_start", "window_envelope_exceeded", "window_exception_expired",
    "grok_tool_surface_unverified", "leg_exec_record_unavailable",
    "leg_auth_signed_out", "leg_auth_unavailable", "leg_execution_failed",
    # claude TUI / Agent View route
    "claude_tui_broker_final_assistant", "claude_tui_broker_terminal_nonconforming",
    "claude_tui_editor_not_ready", "claude_tui_file_output", "claude_tui_missing_canonical_output",
    "claude_tui_pty_eof_no_output", "claude_tui_stalled", "claude_tui_submit_failed",
    "claude_tui_unsupported_platform", "claude_tui_workspace_trust_blocked",
    # agent-harness#1176: the provider's own journaled give-up, or a turn that ended unaccepted
    "claude_seat_output_budget_exhausted", "claude_seat_rate_limited", "claude_seat_provider_api_error",
    "claude_seat_usage_limited", "claude_seat_transcript_rejected",
    # agent-harness#1433 / agent-harness#1434: the turn ended, and the route could not accept its output
    "claude_seat_delivery_refused",
    "claude_agent_session_id_missing", "brokered_claude_session_collision",
    "brokered_claude_transcript_cleanup_failed", "missing_claude_cli",
    "claude_version_probe_timeout", "claude_version_probe_failed", "claude_version_unparseable",
    "subscription_auth_unproven", "tui_adapter_required", "tui_backing_required",
    "under_claude_code", "native_adapter_required", "native_fill", "unavailable",
    # the headless print route (Stage 1b)
    "claude_print_result", "claude_print_subscription_unproven", "claude_print_auth_drift",
    "claude_print_stalled", "panel_claude_route_invalid",
    # the transport seam (Stage 2): `sdk` is named but not admitted (EC-REVIEWTRUTH-18)
    "panel_claude_transport_not_admitted",
    # the jailed transport seam (SEATS CLAUDE, IF-0-CLAUDE-1): `claude_seat_transport.CODES`
    "claude_seat_api_key_source", "claude_sdk_provenance_refused",
    "claude_sdk_worker_contract_violation", "claude_seat_login_unproven",
    "claude_seat_result_unproven", "claude_seat_stream_unsafe",
    "claude_sdk_dependency_unavailable", "claude_sdk_worker_unavailable",
    # route / authorization refusals
    "missing HARDEN review authorization", "missing or forged HARDEN review authorization",
    "harden_advisory_execution_refused", "harden_review_capture_route_refused",
    "harden_review_gateway_route_refused", "harden_review_research_route_refused",
    "harden_review_unsupported_route_refused", "unbound_direct_review_invocation_refused",
    "unbound_review_execution_replacement_refused", "HARDEN review has no canonical repository authority",
    "brokered route rejects capture and research transports", "brokered route rejects empty prompt",
    "broker completed without a response", "research_profile_unenforceable",
    "research_profile_unavailable", "review_operation_cancelled", "review_monitoring_write_failed",
    "codex leg deadline exceeded",
    "review_monitoring_policy_mismatch", "review_monitoring_policy_invalid",
    "review_monitoring_timeout_conflict", "review_monitoring_unsupported_transport",
    "review_monitoring_unsupported_api_fallback",
    # SEATS CLAUDE (agent-harness#1820): a W0 board composed other than its pinned lineup
    "claude_w0_lineup_mismatch",
    # agent-harness#896: placement refusals
    "sandbox_placement_required_unavailable", "sandbox_placement_driver_unavailable",
    # agent-harness#896: the placement driver's codes (typed notices in seat_jail.NOTICES)
    "sandbox_placement_ref_invalid", "sandbox_placement_capability_undeclared",
    "sandbox_placement_plugin_unavailable", "sandbox_placement_backend_unregistered",
    "sandbox_placement_lost_after_launch", "sandbox_placement_end_reached",
    "sandbox_placement_capability_unmet", "sandbox_placement_capacity_exhausted",
    "sandbox_placement_unreachable", "sandbox_placement_not_enrolled",
    "sandbox_placement_identity_mismatch", "sandbox_placement_refused",
    "sandbox_placement_workload_unsupported", "sandbox_placement_operation_timeout",
    "sandbox_placement_code_invalid", "sandbox_placement_release_unconfirmed",
    "sandbox_placement_at_capacity", "sandbox_placement_budget_spent",
    "sandbox_placement_local_release_unconfirmed",
    "seat_placement_waiting",
    # agent-harness#1222: the seat-launch owner's refusals (typed notices in seat_jail.NOTICES)
    "seat_owner_unavailable", "seat_bind_source_unavailable", "seat_broker_socket_unavailable",
    "seat_broker_socket_path_too_long",
    "seat_resource_caps_unavailable",
    "seat_launch_owner_required", "seat_output_path_unavailable", "seat_profile_unavailable",
    "seat_provider_unavailable", "seat_dependency_authority_missing", "seat_filtered_egress_unavailable",
    "executor_review_route_unsupported", "gemini_credential_near_expiry",
    "gemini_credential_refresh_timeout", "seat_keyring_unavailable",
    "claude_agent_view_review_unsupported", "claude_tui_journal_collection_refused",
    "agy_image_unqualified", "seat_output_inside_readonly_input",
    "seat_output_retained_after_teardown",
    # agent-harness#1333: per-host CLI qualification refusals (typed notices in seat_jail.NOTICES)
    "seat_cli_unqualified", "seat_cli_qualification_failed", "seat_cli_qualification_unavailable",
    "seat_cli_qualification_store_unsafe", "seat_cli_adapter_missing", "seat_cli_platform_unsupported",
    # gemini (the broker's fixed vocabulary, folded in)
    "gemini_heartbeat_broker_required", "gemini_heartbeat_capability_unavailable",
    "gemini_heartbeat_admission_handshake_failed", "gemini_broker_diagnostic_invalid",
    "gemini_broker_diagnostic_status_mismatch",
    # agent-harness#1076 first-use self-qualification refusals
    "gemini_heartbeat_self_qualification_failed", "gemini_heartbeat_self_qualification_unavailable",
    "gemini_heartbeat_self_qualification_store_unsafe", "gemini_heartbeat_provenance_unavailable",
    "gemini_heartbeat_provenance_unverified", "gemini_heartbeat_platform_unsupported",
    "Gemini broker stream rejected: malformed JSON",
    "Gemini broker stream rejected: malformed stream event",
    "Gemini broker stream rejected: tool or subagent activity observed",
    "Gemini broker stream changed or omitted its conversation",
    "Gemini broker stream has an incomplete ingestion result sequence",
    "Gemini broker stream has a malformed chunk acknowledgement",
    "Gemini broker stream has no successful terminal response",
    "Gemini broker stream final response reports truncation",
    "Gemini broker native exit without an accepted review",
    "Gemini broker native print timeout",
    "Gemini broker native timeout under heartbeat-only", "Gemini broker deadline exceeded",
    "Gemini broker denied a tool permission without review text",
    "Gemini broker completed without review text", "Gemini broker response lacks a terminal verdict",
    "Gemini broker local provider failure",
    "brokered Gemini subscription credential reference is unavailable",
    "brokered Gemini subscription credential reference is invalid",
    # the review-isolation / broker refusals this runtime raises (their messages are ours)
    'HARDEN broker requires canonical bwrap and python3',
    'HARDEN president authorization does not match this operation',
    'HARDEN president authorization expired before activation',
    'HARDEN president authorization is not active',
    'HARDEN president authorization is not available for activation',
    'HARDEN president isolation requires Linux',
    'HARDEN president route occurrence already consumed',
    'HARDEN review authorization expired before activation',
    'HARDEN review authorization is closed',
    'HARDEN review authorization is not active',
    'HARDEN review authorization is not available for activation',
    'HARDEN review canonical repository authority mismatch',
    'HARDEN review composition requires Linux',
    'HARDEN review has no canonical repository authority',
    'HARDEN review isolation requires a Linux review operation',
    'HARDEN review leg capability already consumed',
    'HARDEN review route occurrence already consumed',
    'HARDEN review staged input does not match authorization',
    'HARDEN review staged input is writable',
    'HARDEN review staged tree does not match authorization',
    'HARDEN review staged tree is missing',
    'HARDEN review staged tree is unreadable',
    'broker authorization expired',
    'broker canonical repository authority is not probeable',
    'broker child response grammar',
    'broker completed without a response',
    'broker frame too large',
    'broker inference adapter is not initially quiescent',
    'broker inference adapter requires cancellation and quiescence',
    'broker operation cancelled or closed',
    'broker peer ancestry mismatch',
    'broker request binding',
    'broker request grammar',
    'broker requires a quiescent cancellable inference adapter',
    'broker response grammar',
    'broker route is not authorized',
    'broker stage is not immutable and bound',
    'brokered Gemini model is not the authorized HARDEN route',
    'brokered Gemini prompt has an invalid UTF-8 boundary',
    'brokered Gemini prompt is empty',
    'brokered Gemini prompt is outside the sealed transport bound',
    'brokered Gemini subscription credential reference is invalid',
    'brokered Gemini subscription credential reference is unavailable',
    'brokered review input contains its digest-bound frame delimiter',
    'brokered review input envelopes bind different Git identities',
    'brokered review input exceeds sealed transport bound',
    'brokered review input pairs a generated envelope with free text',
    'capture-enabled board does not permit research seats',
    'capture-enabled board requires a provider authority for every seat',
    'capture-enabled board requires exactly one resolved Gemini seat',
    'capture-enabled board requires the production Gemini spawn path',
    'capture-enabled board requires unique provider and seat identities',
    'gemini_bounded_deadline_invalid',
    'gemini_broker_diagnostic_invalid',
    'gemini_broker_diagnostic_status_mismatch',
    'gemini_heartbeat_monitor_required',
    'invalid HARDEN president leg authority',
    'invalid HARDEN review launch authorization',
    'invalid HARDEN review leg authority',
    'invalid broker frame label',
    'malformed stream event',
    'malformed stream step',
    'malformed terminal stream result',
    'missing HARDEN review invocation lease',
    'missing HARDEN review leg claim',
    'missing or forged HARDEN president authorization',
    'missing or forged HARDEN review authorization',
    'missing, forged, or expired HARDEN composition authorization',
    'no claude seat is deferred to the driving session under this routing',
    'panel requests must use metadata_only redaction posture',
    'peer credentials unavailable',
    'president broker isolation requires a canonical repository',
    'provider refusal state must be adapter-originated',
    'research policy mismatch',
    'review_monitoring_policy_invalid',
    'review_monitoring_policy_mismatch',
    'review_monitoring_timeout_conflict',
    'review_monitoring_unsupported_api_fallback',
    'review_monitoring_unsupported_route',
    'review_monitoring_unsupported_route:native_fill',
    'review_monitoring_unsupported_route:claude',
    'review_monitoring_unsupported_route:codex',
    'review_monitoring_unsupported_route:gemini',
    'review_monitoring_unsupported_route:grok',
    'review_monitoring_unsupported_route:opencode',
    'review_monitoring_unsupported_route:pi',
    'review_monitoring_unsupported_route:cursor',
    'review_monitoring_unsupported_route:unresolved',
    'review_monitoring_unsupported_transport',
    'seats and legs must correspond positionally',
    'tool or subagent activity observed',
    'truncated broker frame',
    'unexpected stream event',
    'unknown generated review input kind',
    'unsupported owned provider',
    'unsupported owned provider capability policy',
    'unverifiable broker proc stat',
    # agent-harness#1132 seat-jail notices (F030): each code is an exact literal, one per
    # sub-code, never a template. `seat_jail.NOTICES` renders their what/why/fix; a test
    # holds the two sets in step.
    "seat_sandbox_unavailable_host", "seat_sandbox_unavailable_seat_uid",
    "seat_sandbox_unavailable_tiocsti", "seat_sandbox_not_staged",
    "seat_sandbox_refused:jail_build", "seat_sandbox_refused:namespace",
    "seat_sandbox_refused:identity", "seat_sandbox_refused:jail_unqualified",
    "seat_sandbox_refused:pass_store_unsafe", "seat_sandbox_refused:preseed",
    "seat_sandbox_refused:token_file_unsafe", "seat_sandbox_refused:gemini_credential_unsafe",
    "seat_sandbox_refused:gemini_proxy_token_missing", "seat_sandbox_refused:gemini_proxy_url_invalid",
    "seat_sandbox_refused:stage_not_private", "seat_sandbox_refused:stage_changed",
    "seat_sandbox_refused:output_unsafe", "seat_sandbox_retained_after_teardown",
    "seat_sandbox_egress_opt_out", "seat_sandbox_root_fell_back", "seat_sandbox_root_unapplied",
    "seat_staging_below_floor", "seat_filesystem_unconfined", "seat_tool_denied",
    "claude_seat_token_missing", "claude_seat_token_rejected", "claude_seat_token_in_output",
    "claude_seat_token_rate_limited", "claude_seat_bypass_ack_blocked",
    "claude_seat_login_rate_limited", "claude_seat_login_rejected",
    "claude_seat_override_other_subscription",
    "claude_seat_login_token_expired", "claude_seat_login_token_expiring",
    "claude_seat_login_token_awaiting_refresh",
    "seat_jail_qualification_failed",
    # agent-harness#1823: the qualification board's watcher could not start. A detail code
    # only, not a seat notice: the mode-line closure (`seat_route_contract`) is unchanged.
    "seat_sandbox_refused:watch_unavailable",
    # agent-harness#1407: a Gemini seat waiting for its agy login to expire (never a refusal)
    "gemini_credential_awaiting_refresh",
    "gemini_seat_credential_missing", "gemini_seat_credential_unusable",
    "gemini_seat_token_scope_excess", "gemini_seat_stream_split_unavailable",
    "gemini_seat_profile_unqualified", "gemini_seat_token_expired", "gemini_seat_token_in_output",
    "gemini_seat_egress_unconfined", "gemini_seat_token_refreshed_in_jail",
    "gemini_seat_subagent_or_unknown_event", "native_seat_unavailable_heartbeat_only",
    # agent-harness#1170: the jailed Gemini seat's egress proxy cannot run on this host
    "gemini_seat_egress_unavailable",
    # agent-harness#1170: the agy qualification worker's leg on a host that could jail it
    "gemini_seat_qualification_candidate",
    "seat_prompt_over_cap", "seat_identity_unverified",
    # agent-harness#1335: the seat's own command sandbox could not start
    "seat_tool_sandbox_unavailable",
    # board skips
    "skip: omnigent gateway unavailable",
    # claude opus fallback (agent-harness#188)
    "opus_fallback_used", "opus_fallback_classifier_refusal",
    # network-egress isolation refusals (sandbox_egress's own reasons)
    "egress isolation unavailable; refusing to launch WITHOUT network restriction",
    "egress isolation yielded an empty launch prefix",
    "network namespace did not come up; launch is UNISOLATED",
    "the namespace came up but cannot resolve a hostname; a seat here could reach raw IPs "
    "and nothing else (round-6 failure mode)",
    # SEATS GROK, IF-0-GROK-1: the jailed Grok seat's codes (rows in seat_jail.NOTICES)
    "grok_seat_credential_missing", "grok_seat_credential_refused", "grok_seat_token_expired",
    "grok_seat_token_in_output", "grok_seat_token_refreshed_in_jail",
}) | frozenset(_seat_route_contract.CODES) | _seat_jail.CODEX_SEAT_CODES  # IF-0-CODEX-5

RESEARCH_AUDIT_STATUSES: tuple[str, ...] = ("denied", "failed", "no_calls", "unavailable")

UNKNOWN_DETAIL: str = "unknown failure; CLI output not retained"

# Failure templates with NO field: a plain string equal to one of these is our own literal.
PARAMETER_FREE_FAILURES: frozenset[str] = frozenset({
    "timeout", "auth_failure", "usage_limit", "tool_denied: headless tool permission auto-denied",
    "env_failure: temp dir unusable", "env_failure: app-server socket dir not user-owned",
    "env_failure: sandbox command could not be built",
    "env_failure: staging filesystem below its free-space floor",
    "env_failure: no disk-backed scratch and RAM fallback refused", UNKNOWN_DETAIL,
})

#: Closed set of core notice and leg-detail codes that a placement backend may never
#: register as its own refusal code (agent-harness#1501).
RESERVED_DETAIL_VOCABULARY: frozenset[str] = (
    frozenset(_seat_jail.NOTICES)
    | frozenset(_seat_route_contract.OD10_CLASSES)
    | frozenset(_seat_route_contract.CODES)
    | HARNESS_DETAIL_CODES
    | PARAMETER_FREE_FAILURES
    | frozenset(f"research_audit_{status}" for status in RESEARCH_AUDIT_STATUSES)
)
