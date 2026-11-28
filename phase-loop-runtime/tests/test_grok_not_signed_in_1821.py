"""agent-harness#1821: Grok CLI "Not signed in" yields the typed
``grok_seat_credential_missing`` auth notice with its fix line instead of
``unknown failure (exit 1)``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

import pytest

from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.cli import _board_notices_json
from test_grok_seat_jail import _run as _run_jailed_grok
from test_grok_seat_jail import leg as jailed_grok_leg

__all__ = ["jailed_grok_leg"]  # pytest fixture imported for the jailed Grok case


_ISSUE_1821_CLI_LOG = (
    'warning: --tools "run_terminal_command" names no tool, so other tools stay available\n'
    "Not signed in. To authenticate without a browser, run:\n"
    "  grok login --device-code\n\n"
    "Alternatively, set the XAI_API_KEY environment variable or run `grok login` "
    "on a machine with a browser.\n"
    "Error: Not signed in. To authenticate without a browser, run:\n"
    "  grok login --device-code\n\n"
    "Alternatively, set the XAI_API_KEY environment variable or run `grok login` "
    "on a machine with a browser.\n"
)


def _assert_grok_missing_notice(leg: pi.PanelLegResult) -> None:
    assert leg.status == "DEGRADED"
    assert not leg.usable
    assert not leg.text.strip(), "CLI error banner must stay out of review text"
    assert leg.detail == "grok_seat_credential_missing"
    (notice,) = leg.seat_notices
    assert notice.code == "grok_seat_credential_missing"
    assert notice.what == "seat unavailable"
    assert "not signed in" in notice.why.lower()
    assert "`grok login`" in notice.fix
    assert "--device-code" in notice.fix
    assert [n.code for n in pi.refused_seat_notices([leg])] == ["grok_seat_credential_missing"]
    assert [n["code"] for n in _board_notices_json([leg])] == ["grok_seat_credential_missing"]


def test_direct_grok_not_signed_in_surfaces_typed_notice_and_warns_without_voting(
    tmp_path, monkeypatch,
):
    """Exact reproduction of agent-harness#1821 on an unconfined Grok seat."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", _ISSUE_1821_CLI_LOG))

    panel = pi.invoke_panel("ARTIFACT", ["grok"])
    (leg,) = panel.legs
    _assert_grok_missing_notice(leg)

    findings = gr._findings_from_panel(panel)
    assert [f.code for f in findings] == ["seat_notice", "panel_leg_degraded"]
    assert all(f.severity == "warn" for f in findings)
    assert "grok_seat_credential_missing" in findings[0].reason
    assert "--device-code" in findings[0].reason
    assert "grok_seat_credential_missing" in findings[1].reason


def test_direct_grok_not_signed_in_on_stdout_clears_text_so_it_never_blocks_as_nonconforming(
    tmp_path, monkeypatch,
):
    """If the Grok CLI writes the sign-in banner to stdout, `text` is cleared so
    `governed_review` emits warnings rather than a `panel_nonconforming` block."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, _ISSUE_1821_CLI_LOG, ""))

    panel = pi.invoke_panel("ARTIFACT", ["grok"])
    (leg,) = panel.legs
    _assert_grok_missing_notice(leg)

    findings = gr._findings_from_panel(panel)
    assert [f.code for f in findings] == ["seat_notice", "panel_leg_degraded"]
    assert all(f.severity == "warn" for f in findings)


def test_grok_not_signed_in_survives_retained_leg_exec_unavailable_host_probe(
    tmp_path, monkeypatch,
):
    """`_retained_leg_exec` keeps the typed `grok_seat_credential_missing` detail even
    when the turnless Grok host probe returns `unavailable` (CONTRACTS.md)."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

    def fake_exec_leg(*args, **kwargs):
        observation = pi._EXEC_OBSERVATION.get()
        if observation is not None:
            pi._note_exec_result(1, ["grok", "-p", "prompt"], {"PATH": "/usr/bin"}, actual=True)
            observation.update(model_turn=False, verdict=False)
        return 1, "", _ISSUE_1821_CLI_LOG

    monkeypatch.setattr(pi, "_exec_leg", fake_exec_leg)

    panel = pi.invoke_panel("ARTIFACT", ["grok"])
    (leg,) = panel.legs
    _assert_grok_missing_notice(leg)

    (record_path,) = list(state.rglob("leg-*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["vendor"] == "grok"
    assert record["auth_state"] == "unavailable"
    assert record["outcome"] == "leg_auth_unavailable"


def test_brokered_unconfined_grok_not_signed_in_surfaces_typed_notice(
    tmp_path, monkeypatch,
):
    """Brokered (unconfined) Grok legs also surface `grok_seat_credential_missing`."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_has_injected_review_execution_seam", lambda **k: False)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (None, [], None))
    monkeypatch.setattr(pi, "_grok_leg_on_frozen_basis", lambda **k: False)
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", _ISSUE_1821_CLI_LOG))

    artifact = "ARTIFACT"
    brief = pi._resolve_brief("review", None)
    grok_model = backing.harden_subscription_model("grok", pi.DEFAULT_LEG_MODELS["grok"], "high")
    auth = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1",
        purpose="agent-harness#1821 brokered unconfined grok test",
        input_sha256=hashlib.sha256(artifact.encode("utf-8")).hexdigest(),
        instructions_sha256=hashlib.sha256(brief.encode("utf-8")).hexdigest(),
        broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(("grok", grok_model),),
        readonly_tools=backing._REVIEW_READONLY_TOOLS,
        child_credentialless=True,
        child_network_egress=False,
        live_tree_exposed=False,
        api_fallback=False,
        canonical_repo_sha256=backing._canonical_repo_digest(None),
        issued_monotonic_ns=time.monotonic_ns(),
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=None,
    )
    backing._remember_lease(auth)
    backing._lease_for(auth).active = True
    spawned = pi._default_spawn(
        "grok",
        artifact,
        mode="review",
        model=pi.DEFAULT_LEG_MODELS["grok"],
        effort="high",
        review_authorization=auth,
    )
    assert tuple(spawned)[0] == "DEGRADED"
    assert tuple(spawned)[1] == ""
    assert pi._finalize_leg_detail(tuple(spawned)[2]) == "grok_seat_credential_missing"
    assert "grok_seat_credential_missing" in spawned.seat_notices

    panel = pi.invoke_panel(artifact, ["grok"], spawn=lambda leg, art: spawned)
    (leg,) = panel.legs
    _assert_grok_missing_notice(leg)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux seat jail")
def test_jailed_grok_cli_not_signed_in_surfaces_typed_notice(jailed_grok_leg, monkeypatch):
    """If a jailed Grok CLI still exits non-zero reporting `Not signed in`, the jailed
    leg returns DEGRADED with `grok_seat_credential_missing` and empty text."""
    seat = jailed_grok_leg.prepare()
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness",
        lambda *a, **k: pi._LegRun(1, "", _ISSUE_1821_CLI_LOG),
    )
    status, text, failures, _evidence = _run_jailed_grok(seat)
    assert (status, text) == ("DEGRADED", "")
    assert failures == ["grok_seat_credential_missing"]


def test_ok_grok_review_mentioning_not_signed_in_is_never_demoted(tmp_path, monkeypatch):
    """ah#252 invariant: a conforming rc==0 review mentioning `Not signed in` stays OK."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    body = (
        "Checked error handling:\n"
        "Not signed in. To authenticate without a browser, run `grok login --device-code`.\n\n"
        "AGREE\n"
    )
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (0, body, "Error: Not signed in.\n"))

    panel = pi.invoke_panel("ARTIFACT", ["grok"])
    (leg,) = panel.legs
    assert leg.status == "OK"
    assert leg.usable
    assert leg.detail is None
    assert leg.seat_notices == ()


def test_grok_not_signed_in_respects_precedence_and_no_false_positives():
    """Process facts, runtime harness codes, higher-precedence labels, non-grok legs,
    mid-sentence prose, and rc==0 non-conforming bodies are not reclassified."""
    # ANSI-colored banner still matches on Grok rc==1.
    ansi_banner = "\x1b[31mError:\x1b[0m Not signed in. Run `grok login`.\n"
    detail = pi._leg_failure_detail("ERROR", 1, "", ansi_banner, leg="grok")
    assert pi._finalize_leg_detail(detail) == "grok_seat_credential_missing"

    # Non-grok leg is unaffected.
    other = pi._leg_failure_detail("ERROR", 1, "", _ISSUE_1821_CLI_LOG, leg="codex")
    assert pi._finalize_leg_detail(other) != "grok_seat_credential_missing"

    # Process facts (timeout / signal) win over CLI text.
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail("TIMEOUT", 124, "", _ISSUE_1821_CLI_LOG, leg="grok")
    ) == "timeout"
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail("ERROR", -9, "", _ISSUE_1821_CLI_LOG, leg="grok")
    ) == "signal 9"

    # Runtime-emitted _HarnessCode wins over text.
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail(
            "ERROR", 1, _ISSUE_1821_CLI_LOG, pi._HarnessCode("grok_tool_surface_unverified"),
            leg="grok",
        )
    ) == "grok_tool_surface_unverified"

    # Usage limit takes precedence over not-signed-in banner.
    usage = "You hit your weekly limit.\nError: Not signed in.\n"
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail("DEGRADED", 1, "", usage, leg="grok")
    ) == "usage_limit"

    # Mid-sentence prose on rc==1 does not false-positive.
    prose = "The test verified that an operator who is not signed in gets rejected.\n"
    assert not pi._grok_not_signed_in(1, prose, "")
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail("ERROR", 1, prose, "", leg="grok")
    ).startswith("unknown failure")

    # rc==0 with non-conforming review prose starting a line with "Not signed in" stays unlabeled.
    assert not pi._grok_not_signed_in(0, "Not signed in is handled in login.py\n", "")
    assert pi._leg_failure_detail(
        "DEGRADED", 0, "Not signed in is handled in login.py\n", "", leg="grok"
    ) is None

    # rc==0 with empty stdout and stderr banner IS classified.
    assert pi._grok_not_signed_in(0, "", _ISSUE_1821_CLI_LOG)
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail("EMPTY", 0, "", _ISSUE_1821_CLI_LOG, leg="grok")
    ) == "grok_seat_credential_missing"
