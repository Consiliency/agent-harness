"""Every seat-launch owner refusal is a typed notice with a fix line (agent-harness#1222).

A seat is never silently toolless: when the owner refuses or degrades a launch, the leg
carries the owner's own code as its detail and a rendered notice that says what happened,
why, and what the operator does about it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, seat_jail

OWNER_CODES = (
    "seat_owner_unavailable", "seat_bind_source_unavailable", "seat_broker_socket_unavailable",
    "seat_launch_owner_required", "seat_output_path_unavailable", "seat_profile_unavailable",
    "seat_provider_unavailable", "seat_filtered_egress_unavailable",
    "executor_review_route_unsupported", "gemini_credential_near_expiry",
    "gemini_credential_refresh_timeout", "seat_keyring_unavailable",
    "claude_agent_view_review_unsupported", "claude_tui_journal_collection_refused",
    "agy_image_unqualified",
)


def test_the_owner_code_list_is_every_code_the_owner_raises():
    package = Path(pi.__file__).parent
    raised = set()
    for source in ("panel_invoker.py", "launcher.py", "agy_integrity.py"):
        raised |= set(re.findall(
            r'(?:SeatIdentityUnverified|EgressUnavailable|AgyImageUnqualified)\("([a-z_]+)"\)',
            (package / source).read_text(encoding="utf-8")))
    assert raised <= set(OWNER_CODES), sorted(raised - set(OWNER_CODES))


@pytest.mark.parametrize("code", OWNER_CODES)
def test_each_owner_code_is_a_typed_notice_with_a_fix(code):
    assert code in pi._HARNESS_DETAIL_CODES
    notice = seat_jail.render_notice(code, "codex:a")
    assert notice is not None and notice.what and notice.why and notice.fix
    assert notice.fix not in {"none", "report a defect"} or code == "seat_launch_owner_required"


@pytest.mark.parametrize("code", OWNER_CODES)
def test_an_owner_refusal_reaches_the_leg_as_its_code(code):
    for exc in (sandbox_egress.SeatIdentityUnverified(code), sandbox_egress.EgressUnavailable(code)):
        assert pi._exception_failure(exc) == code
