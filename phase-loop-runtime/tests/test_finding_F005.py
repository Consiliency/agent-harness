"""agent-harness#1282 board round 1, codex F005 falsifier (verbatim)."""

import subprocess

import pytest

from phase_loop_runtime import panel_invoker as pi, sandbox_egress, seat_jail


def test_owner_identity_refusal_has_a_typed_notice_and_fix(monkeypatch):
    monkeypatch.setattr(pi.subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 1, "", ""))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified) as caught:
        pi._require_seat_identity(["/usr/bin/bwrap"])
    detail = pi._exception_failure(caught.value)
    assert isinstance(detail, str), "owner identity refusal becomes an unknown failure"
    notice = seat_jail.render_notice(detail, "codex:a")
    assert notice is not None and notice.fix
