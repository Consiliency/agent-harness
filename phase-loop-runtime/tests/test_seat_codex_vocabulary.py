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
            if code not in CODEX_CODES}
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
