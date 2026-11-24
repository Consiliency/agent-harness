"""SEATS GROK SL-0 (agent-harness#1820): the jailed Grok seat's code vocabulary.

IF-0-GROK-1 ("Codes") adds five ``grok_seat_*`` codes to ``seat_jail.NOTICES``, each with
what, why and fix, and one additive ``seat_route_contract.OD10_CLASSES`` entry. All five are
terminal. No fix line names the key variable, a key credential, or a sealed or inline route.
No existing notice row or classification changes, and neither do the descend and capacity
sets. Nothing emits these codes in this lane; the credential and launch lanes do.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re

import pytest

from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_route_contract as contract


# The IF-0-GROK-1 table: code -> OD-10 class.
GROK_CODES: dict[str, str] = {
    "grok_seat_credential_missing": "ordinary",
    "grok_seat_credential_refused": "ordinary",
    "grok_seat_token_expired": "ordinary",
    "grok_seat_token_in_output": "security",
    "grok_seat_token_refreshed_in_jail": "security",
}
PREFIX = "grok_seat_"

# The two tables at base e91638d7, before SEATS GROK: their size and the sha256 of their
# canonical JSON. Literals, never derived from the production tables, so an edited, removed
# or renamed entry fails. agent-harness#2131 adds `seat_broker_socket_path_too_long`
# (an ordinary refusal) to both. agent-harness#2157 rewords the
# `gemini_seat_token_in_output` notice (why/fix text only; code and class unchanged).
# agent-harness#2175 adds the board-wide `seat_review_bundle_too_large` notice.
BASE_NOTICES = (116, "4cff6080c07f732ad8eefb109bd8b343152c5c2c4132d434303c600fcf5024e6")
BASE_OD10_CLASSES = (139, "ebca95f84e246cdccbdbad324cd89194f9967295de2d9f56f3e0816c58a26266")

BASE_DESCEND_CODES = frozenset({
    "seat_sandbox_unavailable_host",
    "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "seat_egress_not_installed",
})
BASE_CAPACITY_CODES = frozenset({"seat_local_capacity_exhausted"})

# A fix line must not name the key variable, a key credential, or a sealed or inline route.
# The key variable is assembled so the literal never appears in this file.
_KEY_VARIABLE = "XAI" + "_API_" + "KEY"
FORBIDDEN_FIX = re.compile(
    rf"{_KEY_VARIABLE}|api[\s_-]?key|\bkeys?\b|key-based|sealed|inline", re.IGNORECASE)


def _digest(table: dict) -> str:
    raw = json.dumps(table, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def test_the_table_has_five_grok_codes_and_no_others():
    assert len(GROK_CODES) == 5
    published = {code for code in seat_jail.NOTICES if code.startswith(PREFIX)}
    assert published == set(GROK_CODES)
    classified = {code for code in contract.OD10_CLASSES if code.startswith(PREFIX)}
    assert classified == set(GROK_CODES)


@pytest.mark.parametrize("code", sorted(GROK_CODES))
def test_each_code_has_a_complete_notice_row(code):
    what, why, fix = seat_jail.NOTICES[code]
    assert what.strip() and why.strip() and fix.strip()
    assert code in seat_jail.NOTICE_CODES
    notice = seat_jail.render_notice(code, "grok:a")
    assert notice is not None
    assert (notice.code, notice.what, notice.why, notice.fix) == (code, what, why, fix)
    assert seat_jail.SeatSandboxRefused(code).code == code


@pytest.mark.parametrize("code", sorted(GROK_CODES))
def test_each_code_has_one_od10_entry_with_the_table_class(code):
    expected = GROK_CODES[code]
    assert contract.OD10_CLASSES[code] == expected
    in_security = code in contract._SECURITY_CODES
    in_ordinary = code in contract._ORDINARY_CODES
    assert (in_security, in_ordinary) == (expected == "security", expected == "ordinary")


@pytest.mark.parametrize("code", sorted(GROK_CODES))
def test_each_code_is_an_exact_detail_literal(code):
    """F030: a leg detail carrying the code finalizes to the code itself, never the
    unknown-failure template."""
    from phase_loop_runtime import panel_invoker as pi

    assert code in pi._HARNESS_DETAIL_CODES
    assert pi._finalize_leg_detail(code) == code


@pytest.mark.parametrize("code", sorted(GROK_CODES))
def test_no_fix_line_names_the_key_variable_a_key_or_a_sealed_or_inline_route(code):
    _what, _why, fix = seat_jail.NOTICES[code]
    assert not FORBIDDEN_FIX.search(fix), (code, fix)


@pytest.mark.parametrize("probe", [
    _KEY_VARIABLE, "set an API key", "use an api_key", "a key", "the keys",
    "a key-based login", "the sealed route", "an inline credential",
])
def test_the_fix_line_filter_catches_each_forbidden_phrase(probe):
    assert FORBIDDEN_FIX.search(probe)


def test_the_fix_lines_carry_the_plan_gist():
    fixes = {code: seat_jail.NOTICES[code][2] for code in GROK_CODES}
    assert "`grok login`" in fixes["grok_seat_credential_missing"]
    assert "--device-code" in fixes["grok_seat_credential_missing"]
    assert "subscription" in fixes["grok_seat_credential_refused"]
    assert "`grok login`" in fixes["grok_seat_token_expired"]
    assert "never renews" in fixes["grok_seat_token_expired"]
    assert "sign in again" in fixes["grok_seat_token_in_output"]
    assert "containment probe" in fixes["grok_seat_token_refreshed_in_jail"]
    for code, cls in GROK_CODES.items():
        assert ("report the outcome privately" in fixes[code]) == (cls == "security"), code


@pytest.mark.parametrize("code", sorted(GROK_CODES))
def test_every_grok_code_is_terminal(code):
    assert code not in contract.DESCEND_CODES
    assert code not in contract.REMOTE_DESCEND_CODES
    assert code not in contract.CAPACITY_CODES
    assert code not in seat_jail.SEALED_FALLBACK_CODES
    assert code not in seat_jail.JAIL_NOT_RUN_CODES


def test_descend_and_capacity_sets_keep_their_literal_values():
    assert contract.DESCEND_CODES == BASE_DESCEND_CODES
    assert contract.REMOTE_DESCEND_CODES == frozenset()
    assert contract.CAPACITY_CODES == BASE_CAPACITY_CODES


def test_existing_notice_rows_are_byte_identical():
    base = {code: list(row) for code, row in seat_jail.NOTICES.items()
            if not code.startswith(PREFIX)}
    assert (len(base), _digest(base)) == BASE_NOTICES


def test_existing_od10_classes_are_unchanged_and_the_grok_entries_are_the_only_additions():
    base = {code: cls for code, cls in contract.OD10_CLASSES.items()
            if not code.startswith(PREFIX)}
    assert (len(base), _digest(base)) == BASE_OD10_CLASSES
    assert set(contract.OD10_CLASSES) - set(base) == set(GROK_CODES)
    assert not contract._SECURITY_CODES & contract._ORDINARY_CODES
    contract._validate_contract()


def test_the_seat_route_import_closure_passes():
    """``seat_route`` refuses to import when its mode-line closure and OD-10 disagree."""
    seat_route = importlib.import_module("phase_loop_runtime.seat_route")
    closure = seat_route.mode_line_codes()
    assert set(GROK_CODES) <= closure
    assert closure == frozenset(contract.OD10_CLASSES)
