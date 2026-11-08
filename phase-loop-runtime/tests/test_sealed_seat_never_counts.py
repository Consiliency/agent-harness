"""A sealed or toolless review seat is never counted (agent-harness#1244 standing rule).

A seat whose route is not jailed (``seat_jail.SEALED_FALLBACK_CODES``), and a seat with no
jail route that has no staged tree to read, used to run with the bundle inlined and no tools,
return OK, and count toward the reviewer floor. Each is now DEGRADED and not run, with its
route code as the typed detail and the notice table's fix line, so every count that reads
``PanelLegResult.usable`` (the board floor, ``usable``, the landing vote, the governed gate,
the train's recorded reviewers, the president's input) leaves it out.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import time
import types
import unittest.mock

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail

STOP = "gemini_seat_egress_unconfined"


def _auth(staged: bool):
    return types.SimpleNamespace(staged_tree_sha256="a" * 64 if staged else None)


# --------------------------------------------------------------------------------------
# The route decision: a non-jailed route is a refusal, never a sealed launch.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("leg", ["claude", "gemini", "codex", "grok"])
@pytest.mark.parametrize("code", sorted(seat_jail.SEALED_FALLBACK_CODES))
def test_every_sealed_route_code_is_a_refusal(code, leg):
    # General, by route: any leg whose route is not jailed, whatever the code that sent it
    # there (not keyed on the Gemini seat's recorded stop).
    route, notices, refusal = pi._seat_route_for_spawn(
        leg, _auth(True), eligible=True,
        decide=lambda leg, **k: seat_jail.SeatRoute(False, code))
    assert not route.jailed
    assert refusal == code and notices == []
    what, why, fix = seat_jail.NOTICES[code]
    assert why and fix


def test_a_seat_with_no_jail_route_and_no_staged_tree_is_a_refusal():
    # Grok still has no registered jail route. Codex is registered by SL-3 and
    # must never take this exception (its independent control follows below).
    for leg in ("grok",):
        route, notices, refusal = pi._seat_route_for_spawn(
            leg, _auth(False), eligible=True,
        )
        assert not route.jailed and route.code == "seat_sandbox_not_staged"
        assert notices == [] and refusal == "seat_sandbox_not_staged"
        # With a staged tree they keep their (unconfined, tooled) route.
        assert pi._seat_route_for_spawn(leg, _auth(True), eligible=True) == (
            None, ["seat_filesystem_unconfined"], None,
        )


def test_registered_codex_refuses_instead_of_using_the_unconfined_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-login"))
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    route, notices, refusal = pi._seat_route_for_spawn("codex", _auth(False), eligible=True)
    assert not route.jailed and refusal == "seat_sandbox_not_staged" and notices == []
    route, notices, refusal = pi._seat_route_for_spawn("codex", _auth(True), eligible=True)
    assert not route.jailed and route.code == refusal == "codex_seat_credential_missing"
    assert notices == []


def test_the_real_route_decision_for_a_seat_with_no_staged_tree_is_a_refusal():
    # The production `decide_seat_route`, no stub: step 0 decides before any host probe.
    route, notices, refusal = pi._seat_route_for_spawn("claude", _auth(False), eligible=True)
    assert route == seat_jail.SeatRoute(False, "seat_sandbox_not_staged")
    assert refusal == "seat_sandbox_not_staged" and notices == []


# --------------------------------------------------------------------------------------
# The production brokered branch of `_default_spawn`: nothing is launched.
# --------------------------------------------------------------------------------------

class _FakeBroker:
    invoked = 0

    def __init__(self, *_a, **_k):
        self.evidence: dict[str, object] = {}

    def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
        type(self).invoked += 1
        status, text = adapter.invoke()
        return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, {"fake": True}

    def close(self):
        return None


def _brokered(monkeypatch, tmp_path, leg: str, staged: bool):
    assert not pi._has_injected_review_execution_seam(leg=leg)
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(
                            expires_monotonic_ns=time.monotonic_ns() + 10**12))
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    return pi._default_spawn(
        leg, "ARTIFACT", mode="review", model="m",
        review_authorization=_auth(staged), canonical_repo_authority=tmp_path,
    )


@pytest.mark.parametrize("code", sorted(seat_jail.SEALED_FALLBACK_CODES))
def test_every_review_fallback_is_degraded_without_a_sealed_launch(
    monkeypatch, tmp_path, code,
):
    # Path-enter the production resolver at L2 for every former sealed fallback.  The
    # broker is the argv boundary: zero invocations proves no sealed command was built.
    from phase_loop_runtime import seat_profiles

    profile = dataclasses.replace(seat_profiles.profile_for("gemini"), recorded_stop=code)
    monkeypatch.setitem(seat_profiles._REGISTRY, "gemini", profile)
    spawned = _brokered(monkeypatch, tmp_path, "gemini", staged=True)
    assert _FakeBroker.invoked == 0, "a sealed seat was launched"
    assert tuple(spawned) == ("DEGRADED", "", code)
    assert spawned.seat_notices == (code,)


@pytest.mark.parametrize("leg", ["claude", "codex", "grok"])
def test_a_seat_with_no_staged_tree_is_degraded_and_not_run(monkeypatch, tmp_path, leg):
    spawned = _brokered(monkeypatch, tmp_path, leg, staged=False)
    assert _FakeBroker.invoked == 0, "a toolless seat was launched"
    assert tuple(spawned) == ("DEGRADED", "", "seat_sandbox_not_staged")
    assert spawned.seat_notices[0] == "seat_sandbox_not_staged"


# --------------------------------------------------------------------------------------
# The seat modes published before launch say the same thing the spawn does.
# --------------------------------------------------------------------------------------

def _board():
    return types.SimpleNamespace(seats=[
        types.SimpleNamespace(harness=leg, seat_key=f"{leg}:a", model="m")
        for leg in ("claude", "gemini", "codex", "grok")])


def test_seat_modes_name_a_sealed_route_degraded_with_its_fix(monkeypatch):
    from phase_loop_runtime import seat_jail_autoqualify as aq

    from phase_loop_runtime import seat_route
    from phase_loop_runtime.seat_route_contract import RouteDecision

    real = seat_route.resolve

    def _route(request, **kwargs):
        if request.leg == "gemini":
            return RouteDecision(
                leg="gemini", vendor="gemini", mode="degraded", code=STOP, steps=(),
                exception=None, variant=None, qualification_key=None, also=(), lease=None,
            )
        return real(request, **kwargs)

    monkeypatch.setattr(seat_route, "resolve", _route)
    monkeypatch.setattr(pi._seat_jail_autoqualify, "ensure_qualified",
                        lambda leg: aq.Outcome(aq.QUALIFIED))
    monkeypatch.setattr(pi._seat_credentials, "override_decision",
                        lambda adapter=None: pi._seat_credentials.OverrideDecision(False))
    monkeypatch.setattr(pi._seat_credentials, "login_seconds_left", lambda margin_s, **_k: None)
    authorization = _auth(True)
    try:
        modes = pi._seat_launch_modes(
            _board(), mode="review", review_authorization=authorization, base_env={}
        )
        gemini = next(m for m in modes if m.leg == "gemini")
        assert (gemini.mode, gemini.code) == ("degraded", STOP)
        assert gemini.fix == seat_jail.NOTICES[STOP][2] and gemini.fix
        assert "will not run" in gemini.render()
        assert not [m for m in modes if m.mode == "sealed"]
    finally:
        pi._release_cached_routes(authorization)


def test_seat_modes_with_no_staged_tree_are_all_degraded(monkeypatch):
    # The production route decision: no stub. L0's staged-tree check precedes the profile's
    # host, credential, egress, authority and pass-record gates.
    authorization = _auth(False)
    try:
        modes = pi._seat_launch_modes(
            _board(), mode="review", review_authorization=authorization, base_env={}
        )
        assert [(m.leg, m.mode, m.code) for m in modes] == [
            (leg, "degraded", "seat_sandbox_not_staged")
            for leg in ("claude", "gemini", "codex", "grok")
        ]
        assert all(m.fix == seat_jail.NOTICES["seat_sandbox_not_staged"][2] for m in modes)
    finally:
        pi._release_cached_routes(authorization)


# --------------------------------------------------------------------------------------
# What the refusal leaves behind is never counted, and the refusal names its fix.
# --------------------------------------------------------------------------------------

def _refused_gemini():
    leg = pi.PanelLegResult(leg="gemini", status="DEGRADED", text="", detail=STOP,
                            seat_key="gemini:a")
    pi.attach_seat_notices(leg, [STOP])
    return leg


def _codex_ok():
    # A counted seat with a notice of its own: it is never named as not counted.
    leg = pi.PanelLegResult(leg="codex", status="OK", text="Fine.\n\nAGREE", seat_key="codex:a")
    pi.attach_seat_notices(leg, ["seat_filesystem_unconfined"])
    return leg


def _legs():
    # The shape of the 0.7.26/0.7.27 real-CLI board on a host whose Gemini seat is sealed:
    # codex and claude reviewed, grok failed, gemini's route is the recorded stop.
    return (
        _codex_ok(),
        _refused_gemini(),
        pi.PanelLegResult(leg="claude", status="OK", text="Fine.\n\nAGREE", seat_key="claude:a"),
        pi.PanelLegResult(leg="grok", status="DEGRADED", text="", seat_key="grok:a"),
    )


def _run_board(tmp_path, legs, *, json_out: bool):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    real_compose = comp_mod.compose_review_board
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    out, err = io.StringIO(), io.StringIO()
    with (
        unittest.mock.patch.object(
            comp_mod, "compose_review_board",
            side_effect=lambda *a, **k: real_compose(
                is_available=lambda v: v in {"codex", "gemini", "claude", "grok"}),
        ),
        unittest.mock.patch.object(pi, "invoke_board", return_value=pi.PanelResult(legs=legs)),
        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
    ):
        code = cli_main(["advisor-board", *(["--json"] if json_out else []), str(artifact)])
    return code, out.getvalue(), err.getvalue()


def test_a_refused_sealed_seat_is_not_counted_by_the_board(tmp_path):
    code, out, _err = _run_board(tmp_path, _legs(), json_out=True)
    payload = json.loads(out)
    assert code == 1
    assert payload["usable"] is False and payload["delivered_seats"] == 2
    assert payload["independence"]["seats"] == 2
    gemini = next(leg for leg in payload["legs"] if leg["leg"] == "gemini")
    assert (gemini["status"], gemini["detail"]) == ("DEGRADED", STOP)
    assert [n["fix"] for n in gemini["notices"]] == [seat_jail.NOTICES[STOP][2]]
    # The refusal, structured: only the refused seat, never a counted one with a notice.
    assert payload["refused_seats"] == [
        {"seat_key": "gemini:a", "code": STOP, "fix": seat_jail.NOTICES[STOP][2]}]


def test_a_refusal_survives_the_board_into_an_uncounted_leg(monkeypatch, tmp_path):
    # invoke_board's own conversion of the spawn's refusal shape: the leg carries the code
    # as its detail and its notice with the fix, and is not counted.
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
    from phase_loop_runtime.advisor_board.matrix import default_matrix
    from phase_loop_runtime.advisor_board.schema import Board
    from .harden_tdd_guard import invoke_sanctioned_board_control

    def provider(leg, artifact, **kwargs):
        if leg == "gemini":
            return pi._BrokeredSpawnResult("DEGRADED", "", pi._HarnessCode(STOP),
                                           seat_notices=(STOP,))
        return "OK", "Fine.\n\nAGREE"

    monkeypatch.setattr(pi, "_default_spawn_via_provider", provider)
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a, **k: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    seats = tuple(s for s in DEFAULT_SEATS if s.harness in ("codex", "gemini"))
    board = Board(name="codex-gemini", purpose="premerge-review", seats=seats)
    result = invoke_sanctioned_board_control(
        board, "artifact", matrix=default_matrix(env={}, probe=lambda *a: True),
        base_env={}, repo_dir=tmp_path, stream_dir=tmp_path / "stream")
    gemini = next(leg for leg in result.legs if leg.leg == "gemini")
    assert (gemini.status, gemini.detail, gemini.usable) == ("DEGRADED", STOP, False)
    assert [(n.code, n.fix) for n in pi.refused_seat_notices(result.legs)] == [
        (STOP, seat_jail.NOTICES[STOP][2])]
    assert [leg.leg for leg in result.usable_legs] == ["codex"]


def test_the_below_floor_refusal_names_the_uncounted_seat_and_its_fix(tmp_path):
    code, _out, err = _run_board(tmp_path, _legs(), json_out=False)
    assert code == 1
    assert "below the board's independence floor" in err
    fix = seat_jail.NOTICES[STOP][2]
    assert f"not counted: gemini:a [{STOP}] fix: {fix}" in err, err
    assert err.count("not counted:") == 1, err


def test_the_landing_vote_and_president_input_leave_the_seat_out():
    from phase_loop_runtime.agy_qualification import counts_toward_landing

    leg = _refused_gemini()
    assert not leg.usable and not counts_toward_landing(leg)
    seat = types.SimpleNamespace(seat_key="gemini:a")
    findings = pi.president_findings_from_legs((seat,), (leg,))
    assert findings == ("F001: [gemini:a] unusable (DEGRADED)",)


def test_the_governed_floor_hold_names_the_uncounted_seat_and_its_fix():
    # Through the real pre-merge loop: codex reviewed, the gemini seat was refused, so the
    # board holds below its floor and the hold names the refused seat with its fix.
    from phase_loop_runtime.governed_premerge import run_governed_premerge_loop
    from phase_loop_runtime.governed_review import governed_planning_gate

    panel = pi.PanelResult(legs=(_codex_ok(), _refused_gemini()))

    def loop_invoke(**kw):
        return governed_planning_gate(**kw, invoke=lambda art, pool, spawn=None: panel)

    result = run_governed_premerge_loop(
        artifact="ART", author_executor="claude", run_mode="governed",
        available_legs=("codex", "gemini"), invoke=loop_invoke)
    assert not result.mergeable and result.reason == "below_reviewer_floor"
    (floor,) = [f for f in result.findings if f.code == "governed_below_reviewer_floor"]
    fix = seat_jail.NOTICES[STOP][2]
    assert floor.reason.endswith(f" Not counted: gemini:a [{STOP}] fix: {fix}."), floor.reason
    assert "codex:a" not in floor.reason


# --------------------------------------------------------------------------------------
# The one exception: the agy qualification worker measures a candidate image on the
# Gemini route. That process alone sets the heartbeat module's candidate; its leg is
# admitted `qualification_candidate`, which is never a vote.
# --------------------------------------------------------------------------------------

def _stopped(leg, **_k):
    return seat_jail.SeatRoute(False, STOP) if leg == "gemini" else seat_jail.SeatRoute(
        False, "seat_sandbox_unavailable_host")


def test_the_qualification_worker_keeps_the_gemini_route_and_nothing_else(monkeypatch):
    from phase_loop_runtime import gemini_heartbeat as gh

    monkeypatch.setattr(gh, "_CANDIDATE", object())
    route, notices, refusal = pi._seat_route_for_spawn(
        "gemini", _auth(True), eligible=True,
    )
    assert not route.jailed and route.code == "gemini_seat_qualification_candidate"
    assert notices == ["gemini_seat_qualification_candidate"] and refusal is None
    # Only the Gemini leg: any other seat in that process is still refused.
    _route, _notices, refusal = pi._seat_route_for_spawn(
        "claude", _auth(True), eligible=True, decide=_stopped)
    assert refusal == "seat_sandbox_unavailable_host"
    modes = pi._seat_launch_modes(
        types.SimpleNamespace(seats=[types.SimpleNamespace(harness="gemini", seat_key="g",
                                                           model="m")]),
        mode="review", review_authorization=_auth(True), base_env={})
    assert [(m.mode, m.code) for m in modes] == [
        ("native", "gemini_seat_qualification_candidate"),
    ]


def test_outside_the_qualification_worker_the_gemini_route_is_refused(monkeypatch):
    from phase_loop_runtime import gemini_heartbeat as gh

    monkeypatch.setattr(gh, "_CANDIDATE", None)
    assert pi._seat_route_for_spawn("gemini", _auth(True), eligible=True, decide=_stopped)[2] == STOP


def test_a_qualification_candidate_leg_is_never_a_vote():
    from phase_loop_runtime.agy_qualification import counts_toward_landing

    leg = pi.PanelLegResult(leg="gemini", status="OK", text="Fine.\n\nAGREE", seat_key="g")
    object.__setattr__(leg, "_review_monitoring", {"effective_policy": "heartbeat_only"})
    pi.attach_harden_isolation_evidence(leg, {"provider_admission_class": "qualification_candidate"})
    assert leg.usable and not counts_toward_landing(leg)


# --------------------------------------------------------------------------------------
# An advisory run (agent-harness#802) is not a review: it stages no tree on purpose and
# inlines its standalone document whole. Its unstaged seats keep the inline route; nothing
# else does.
# --------------------------------------------------------------------------------------

def _advisory_authorization(tmp_path, monkeypatch):
    # The production path the `--advisory` CLI takes: the advisory contract's digest bound,
    # a private scratch authority, no staged tree.
    from phase_loop_runtime.advisor_board import backing
    from phase_loop_runtime.advisor_board.advisory_contract import ADVISORY_CONTRACT
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from phase_loop_runtime.cli import _advisory_review_authority

    token = backing.set_review_instruction_digest(ADVISORY_CONTRACT)
    try:
        return backing.prepare_review_isolation_authorization(
            DEFAULT_BOARD, "a standalone document\n", mode="review",
            canonical_repo_authority=_advisory_review_authority(tmp_path),
            stage_review_tree=False)
    finally:
        backing.reset_review_instruction_digest(token)


def test_an_advisory_run_keeps_its_unstaged_seats_inline(tmp_path, monkeypatch):
    auth = _advisory_authorization(tmp_path, monkeypatch)
    assert auth.staged_tree_sha256 is None
    route, notices, refusal = pi._seat_route_for_spawn("claude", auth, eligible=True)
    assert (route, notices, refusal) == (None, ["seat_sandbox_not_staged"], None)
    assert pi._seat_route_for_spawn("codex", auth, eligible=True) == (
        None, ["seat_sandbox_not_staged"], None,
    )
    modes = pi._seat_launch_modes(_board(), mode="review", review_authorization=auth, base_env={})
    assert [(m.mode, m.code) for m in modes] == [("sealed", "seat_sandbox_not_staged")] * 4


def test_an_advisory_run_still_refuses_every_other_sealed_code(tmp_path, monkeypatch):
    auth = _advisory_authorization(tmp_path, monkeypatch)
    for code in sorted(seat_jail.SEALED_FALLBACK_CODES - {"seat_sandbox_not_staged"}):
        assert pi._seat_route_for_spawn(
            "gemini", auth, eligible=True,
            decide=lambda leg, code=code, **k: seat_jail.SeatRoute(False, code))[2] == code


def _near_miss_of_the_advisory_digest() -> str:
    from hashlib import sha256

    from phase_loop_runtime.advisor_board.advisory_contract import ADVISORY_CONTRACT

    real = sha256(ADVISORY_CONTRACT.encode("utf-8")).hexdigest()
    return real[:-1] + ("0" if real[-1] != "0" else "1")


@pytest.mark.parametrize("digest", [
    "0" * 64,                              # another brief's digest
    "near-miss",                           # forged: one hex digit off the advisory digest
    None,                                  # no digest bound
])
def test_a_review_run_with_no_staged_tree_is_refused_whatever_its_brief(tmp_path, digest):
    if digest == "near-miss":
        digest = _near_miss_of_the_advisory_digest()
    review = types.SimpleNamespace(staged_tree_sha256=None, instructions_sha256=digest)
    for leg in ("claude", "gemini", "codex", "grok"):
        assert pi._seat_route_for_spawn(leg, review, eligible=True)[2] == "seat_sandbox_not_staged"
