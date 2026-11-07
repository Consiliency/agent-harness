"""TEAMHOST managed-release switch-on and doctor agreement."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime import claude_seat_transport
from phase_loop_runtime import executable_dependency_startup
from phase_loop_runtime import panel_invoker
from phase_loop_runtime import sandbox_egress
from phase_loop_runtime import seat_admission
from phase_loop_runtime import seat_egress_proxy
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_profiles
from phase_loop_runtime import seat_route
from phase_loop_runtime import seat_subject
from phase_loop_runtime.executable_dependency import (
    ExecutableDependencyError,
    admit_executable_dependency,
)


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed seat")


def _managed_world(tmp_path, monkeypatch, *, resolver_code=None, authority_code=None):
    fixture = build_fixture(
        tmp_path / "dependency",
        provider="claude",
        provider_destination=Path(f"{seat_jail.SEAT_BIN}/claude"),
        include_entries=False,
    )
    subject = seat_subject.SeatSubject(
        leg="claude",
        source="managed_release",
        subject_path=fixture.subject,
        release_id="release-a",
        requirement=fixture.requirement,
    )
    events: list[str] = []

    def resolve(_leg, _env):
        events.append("subject")
        if resolver_code is not None:
            raise ExecutableDependencyError(resolver_code)
        return subject

    def open_authority(_subject):
        events.append("authority")
        if authority_code is not None:
            raise ExecutableDependencyError(authority_code)
        return os.dup(fixture.authority_fd), fixture.requirement.expected_authority_sha256

    profile = seat_profiles.profile_for("claude")
    assert profile is not None and profile.projection == "optional"
    doctor_profile = replace(
        profile,
        credential_present=lambda: True,
        preconditions=(),
        recorded_stop=None,
        allowlist_id=None,
    )
    monkeypatch.setattr(seat_subject, "resolve_seat_subject", resolve)
    monkeypatch.setattr(seat_subject, "open_managed_authority", open_authority)
    monkeypatch.setattr(
        executable_dependency_startup,
        "current_dependency_for_provider",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(seat_admission, "_profile_for", lambda _leg: doctor_profile)
    monkeypatch.setattr(seat_admission, "_GATES", {})

    def host_capability():
        events.append("host")
        return None

    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", host_capability)
    monkeypatch.setattr(seat_jail, "jail_profile_digest", lambda _leg, *_args: "d" * 64)
    monkeypatch.setattr(
        seat_jail,
        "pass_record_verdict",
        lambda *_args, **_kwargs: (True, "passed"),
    )
    monkeypatch.setattr(
        claude_seat_transport,
        "resolve_jailed_claude_transport",
        lambda *_args, **_kwargs: ("print", None),
    )
    return fixture, subject, events


def _launch_verdict(env):
    try:
        _subject, dependency = panel_invoker._resolved_jail_subject("claude", env)
    except ExecutableDependencyError as exc:
        return seat_admission.Verdict("claude", "refuses", code=exc.code)
    try:
        return seat_admission.Verdict("claude", "admits")
    finally:
        if dependency is not None:
            dependency.close()


@pytest.mark.parametrize(
    ("state", "resolver_code", "authority_code", "expected"),
    [
        ("valid", None, None, ("admits", None)),
        ("missing_pin", "authority_missing", None, ("refuses", "authority_missing")),
        ("missing_entry", "authority_missing", None, ("refuses", "authority_missing")),
        ("missing_authority", None, "authority_missing", ("refuses", "authority_missing")),
        ("digest_mismatch", None, "authority_invalid", ("refuses", "authority_invalid")),
    ],
)
def test_managed_authority_doctor_and_launch_agree(
    tmp_path, monkeypatch, state, resolver_code, authority_code, expected
):
    fixture, _subject, events = _managed_world(
        tmp_path,
        monkeypatch,
        resolver_code=resolver_code,
        authority_code=authority_code,
    )
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    try:
        doctor = seat_admission.verdict("claude", env, execute=True)
        launch = _launch_verdict(env)
    finally:
        fixture.close()

    assert (doctor.status, doctor.code) == expected
    assert (launch.status, launch.code) == expected
    if resolver_code is None:
        # Launch (seat_route L3 before _projection_for_launch) checks the host first.
        assert events.index("host") < events.index("authority")


def test_optional_profile_launches_the_declared_subject_without_changing_profile_digest(
    tmp_path, monkeypatch
):
    fixture, subject, _events = _managed_world(tmp_path, monkeypatch)
    before = seat_jail.jail_profile_digest("claude", "x86_64")
    try:
        resolved, dependency = panel_invoker._resolved_jail_subject(
            "claude", {"PATH": str(tmp_path), "HOME": str(tmp_path)}
        )
        try:
            assert resolved == subject
            assert dependency is not None
            assert dependency.subject_source == str(fixture.subject)
            assert dependency.subject_destination == f"{seat_jail.SEAT_BIN}/claude"
            assert dependency.projection_digest
        finally:
            dependency.close()
    finally:
        fixture.close()
    assert seat_jail.jail_profile_digest("claude", "x86_64") == before


def test_subject_only_declaration_admits_without_auxiliary_projection_entries(tmp_path):
    fixture = build_fixture(
        tmp_path / "subject-only",
        provider="claude",
        provider_destination=Path(f"{seat_jail.SEAT_BIN}/claude"),
        include_entries=False,
    )
    try:
        assert fixture.declaration["entries"] == []
        admitted = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        try:
            projection = admitted.reopen_projection()
            try:
                assert [entry.destination for entry in projection.entries] == [
                    f"{seat_jail.SEAT_BIN}/claude"
                ]
                assert len(projection.pass_fds) == 1
            finally:
                projection.close()
        finally:
            admitted.close()
    finally:
        fixture.close()


# The JAILCORE route refuses every projection admission failure with its typed identity
# code (``test_seat_route.test_dependency_admission_failure_is_a_typed_identity_refusal``);
# the doctor names the specific authority code so LA1-AUTHORITY-PIN is selected.
_SEAT_CODE = {
    "authority_missing": "seat_sandbox_refused:identity",
    "authority_invalid": "seat_sandbox_refused:identity",
}


def _production_world(
    tmp_path,
    monkeypatch,
    *,
    authority_code=None,
    resolver_code=None,
    host_code=None,
    credential=True,
):
    fixture, _subject, events = _managed_world(
        tmp_path,
        monkeypatch,
        authority_code=authority_code,
        resolver_code=resolver_code,
    )
    real = seat_profiles.profile_for("claude")
    profile = replace(
        real,
        credential_present=lambda: credential,
        preconditions=(),
        recorded_stop=None,
        variant=None,
    )
    monkeypatch.setattr(seat_admission, "_profile_for", lambda _leg: profile)
    monkeypatch.setattr(
        seat_profiles, "profile_for", lambda leg: profile if leg == "claude" else None
    )

    def host_capability():
        events.append("host")
        return host_code

    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", host_capability)
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    return fixture


def _production_refusal():
    _route, _notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude",
        SimpleNamespace(staged_tree_sha256="0" * 64, instructions_sha256=None),
        eligible=True,
    )
    return refusal


_PRODUCTION_STATES = [
    ("authority_missing", "authority_missing", None, None, True, "authority_missing"),
    ("authority_invalid", "authority_invalid", None, None, True, "authority_invalid"),
    ("subject_authority_missing", None, "authority_missing", None, True,
     "authority_missing"),
    ("subject_authority_invalid", None, "authority_invalid", None, True,
     "authority_invalid"),
    ("host_and_authority", "authority_invalid", None, "seat_sandbox_unavailable_host", True,
     "seat_sandbox_unavailable_host"),
    ("host_and_subject_authority", None, "authority_invalid",
     "seat_sandbox_unavailable_host", True, "seat_sandbox_unavailable_host"),
    ("credential_and_authority", "authority_missing", None, None, False,
     "claude_seat_token_missing"),
]


def _agrees(doctor, production):
    return doctor.status == "refuses" and _SEAT_CODE.get(doctor.code, doctor.code) == production


@pytest.mark.parametrize(
    ("state", "authority_code", "resolver_code", "host_code", "credential", "doctor_code"),
    _PRODUCTION_STATES,
    ids=[row[0] for row in _PRODUCTION_STATES],
)
def test_managed_authority_gate_agrees_with_the_production_route(
    tmp_path,
    monkeypatch,
    state,
    authority_code,
    resolver_code,
    host_code,
    credential,
    doctor_code,
):
    fixture = _production_world(
        tmp_path, monkeypatch,
        authority_code=authority_code,
        resolver_code=resolver_code,
        host_code=host_code,
        credential=credential,
    )
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    try:
        doctor = seat_admission.verdict("claude", env, execute=True)
        production = _production_refusal()
    finally:
        fixture.close()
    assert (doctor.status, doctor.code) == ("refuses", doctor_code)
    assert _agrees(doctor, production), (state, doctor, production)


def test_doctor_pass_record_uses_the_projected_launch_key(tmp_path, monkeypatch):
    fixture, _subject, _events = _managed_world(tmp_path, monkeypatch)
    observed = []
    monkeypatch.setattr(
        seat_jail,
        "pass_record_verdict",
        lambda key: (observed.append(key) or True, "passed"),
    )
    monkeypatch.setattr(seat_jail, "host_identity", lambda: "host-fixture")
    monkeypatch.setattr(seat_jail, "falsifier_layout_identity", lambda: "layout-fixture")
    try:
        verdict = seat_admission.verdict(
            "claude", {"PATH": str(tmp_path), "HOME": str(tmp_path)}, execute=True
        )
    finally:
        fixture.close()
    assert verdict.status == "admits"
    assert len(observed) == 1
    assert observed[0].projection_digest
    assert observed[0].profile_digest == "d" * 64


@pytest.mark.parametrize(
    ("exceptions", "expected"),
    [
        ({}, "seat_egress_allowlist_missing"),
        (
            {
                "claude": SimpleNamespace(
                    kind="open egress",
                    expiry=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc),
                )
            },
            "seat_route_exception_expired",
        ),
    ],
)
def test_doctor_applies_the_claude_route_egress_exception(
    tmp_path, monkeypatch, exceptions, expected
):
    fixture, _subject, events = _managed_world(tmp_path, monkeypatch)
    monkeypatch.setattr(
        seat_route,
        "load_route_policy",
        lambda: SimpleNamespace(exceptions=exceptions),
    )
    try:
        verdict = seat_admission.verdict(
            "claude", {"PATH": str(tmp_path), "HOME": str(tmp_path)}, execute=True
        )
    finally:
        fixture.close()
    assert (verdict.status, verdict.code) == ("refuses", expected)
    assert "authority" not in events


def test_removing_the_managed_authority_gate_breaks_doctor_launch_agreement(
    tmp_path, monkeypatch
):
    fixture = _production_world(tmp_path, monkeypatch, authority_code="authority_invalid")
    monkeypatch.setattr(seat_admission, "_managed_authority", lambda *_args: None)
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    try:
        doctor = seat_admission.verdict("claude", env, execute=True)
        production = _production_refusal()
    finally:
        fixture.close()
    assert (doctor.status, doctor.code) == ("admits", None)
    assert production == "seat_sandbox_refused:identity"
    assert not _agrees(doctor, production)


def test_authority_before_host_mutant_breaks_doctor_launch_agreement(tmp_path, monkeypatch):
    fixture = _production_world(
        tmp_path, monkeypatch,
        authority_code="authority_invalid", host_code="seat_sandbox_unavailable_host",
    )
    real_base = seat_admission._base_verdict

    def authority_first(leg, env, execute):
        subject = seat_subject.resolve_seat_subject(leg, env)
        early = seat_admission._managed_authority(leg, subject, seat_admission._profile_for(leg))
        return early if early is not None else real_base(leg, env, execute)

    monkeypatch.setattr(seat_admission, "_base_verdict", authority_first)
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    try:
        doctor = seat_admission.verdict("claude", env, execute=True)
        production = _production_refusal()
    finally:
        fixture.close()
    assert (doctor.status, doctor.code) == ("refuses", "authority_invalid")
    assert production == "seat_sandbox_unavailable_host"
    assert not _agrees(doctor, production)
