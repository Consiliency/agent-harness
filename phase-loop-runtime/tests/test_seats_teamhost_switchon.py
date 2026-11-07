"""TEAMHOST managed-release switch-on and doctor agreement."""

from __future__ import annotations

import ast
from dataclasses import replace
import inspect
import os
from pathlib import Path
import sys
import textwrap

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime import claude_seat_transport
from phase_loop_runtime import executable_dependency_startup
from phase_loop_runtime import panel_invoker
from phase_loop_runtime import seat_admission
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_profiles
from phase_loop_runtime import seat_subject
from phase_loop_runtime.executable_dependency import ExecutableDependencyError


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed seat")


def _managed_world(tmp_path, monkeypatch, *, resolver_code=None, authority_code=None):
    fixture = build_fixture(
        tmp_path / "dependency",
        provider="claude",
        provider_destination=Path(f"{seat_jail.SEAT_BIN}/claude"),
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
        assert events.index("authority") < events.index("host") if "host" in events else True
    if authority_code is not None:
        assert "host" not in events


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


def test_removing_the_managed_authority_gate_breaks_doctor_launch_agreement(
    tmp_path, monkeypatch
):
    fixture, _subject, _events = _managed_world(
        tmp_path, monkeypatch, authority_code="authority_invalid"
    )
    source = textwrap.dedent(inspect.getsource(seat_admission._base_verdict))
    tree = ast.parse(source)
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    managed_gates = [
        node
        for node in function.body
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "subject.source == 'managed_release'"
    ]
    assert len(managed_gates) == 1
    function.body.remove(managed_gates[0])
    namespace = dict(seat_admission.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<missing-managed-authority-gate>", "exec"), namespace)
    monkeypatch.setattr(seat_admission, "_base_verdict", namespace["_base_verdict"])
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    try:
        doctor = seat_admission.verdict("claude", env, execute=True)
        launch = _launch_verdict(env)
    finally:
        fixture.close()

    assert (doctor.status, doctor.code) == ("admits", None)
    assert (launch.status, launch.code) == ("refuses", "authority_invalid")
