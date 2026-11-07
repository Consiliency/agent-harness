"""TEAMHOST integration at the existing review-seat launch seams."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime import agy_qualification
from phase_loop_runtime import executable_dependency_startup
from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime import seat_qualification_key
from phase_loop_runtime import seat_keyring_exec
from phase_loop_runtime import seat_subject
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.executable_dependency import ExecutableDependencyError


def _subject(leg: str, source: str, path: Path | None) -> seat_subject.SeatSubject:
    return seat_subject.SeatSubject(leg, source, path, None, None)  # type: ignore[arg-type]


def _install_gemini_dependency(tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / "dependency", provider="gemini")
    carrier = SimpleNamespace(
        requirement=fixture.requirement,
        borrowed_authority_fd=fixture.authority_fd,
        expected_authority_sha256=fixture.requirement.expected_authority_sha256,
    )
    admitted = []
    real_admit = seat_qualification_key.admit_executable_dependency

    def record_admission(*args, **kwargs):
        dependency = real_admit(*args, **kwargs)
        admitted.append(dependency)
        return dependency

    monkeypatch.setattr(
        executable_dependency_startup,
        "current_dependency_for_provider",
        lambda *_args, **_kwargs: carrier,
    )
    monkeypatch.setattr(
        seat_qualification_key, "admit_executable_dependency", record_admission,
    )
    return fixture, admitted


def _close_gemini_dependency(fixture, admitted):
    for dependency in admitted:
        dependency.close()
    fixture.close()


def test_seat_provider_source_and_profile_use_the_subject_resolver(tmp_path, monkeypatch):
    executable = tmp_path / "claude-native"
    executable.write_bytes(b"fixture provider")
    executable.chmod(0o700)
    calls: list[tuple[str, dict[str, str]]] = []

    def resolve(leg, env):
        calls.append((leg, dict(env)))
        return _subject(leg, "standalone", executable)

    monkeypatch.setattr(panel, "integrated_seat_subject", resolve)
    monkeypatch.setattr(
        panel._seat_credentials,
        "resolve_claude_seat_credential",
        lambda *_args, **_kwargs: SimpleNamespace(token=b"synthetic-token"),
    )
    env = {"HOME": str(tmp_path), "PATH": str(tmp_path)}

    harness, resolved = panel._seat_provider_source("claude", env)
    assert (harness, Path(resolved)) == ("claude", executable)

    with panel.seat_profile(
        harness="claude",
        executable="claude",
        env=env,
        cwd=tmp_path,
        role=panel.SeatLaunchRole.PROVIDER_ADMIN,
    ) as (provider, profile):
        assert provider == "/run/phase-loop-seat/provider"
        assert str(executable) in profile.mount_args

    assert [leg for leg, _env in calls] == ["claude", "claude"]


def test_refused_managed_subject_reaches_no_spawn(tmp_path, monkeypatch):
    refusal = ExecutableDependencyError("authority_missing")
    monkeypatch.setattr(
        panel,
        "integrated_seat_subject",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(refusal),
    )
    monkeypatch.setattr(
        panel,
        "launch_provider",
        lambda *_args, **_kwargs: pytest.fail("provider spawned after subject refusal"),
    )

    with pytest.raises(ExecutableDependencyError) as caught:
        panel.run_provider(
            ["claude", "--version"],
            cwd=tmp_path,
            env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
        )
    assert caught.value.code == "authority_missing"


def test_keyring_helper_uses_the_bind_source_check(monkeypatch):
    checked: list[Path] = []
    real_check = panel._seat_bind_source

    def check(path, **kwargs):
        checked.append(Path(path))
        return real_check(path, **kwargs)

    marker = object()
    monkeypatch.setattr(panel, "_seat_bind_source", check)
    monkeypatch.setattr(panel, "launch_provider", lambda *_args, **_kwargs: marker)

    result = panel.launch_owned(
        ["claude", "--version"],
        role=panel.SeatLaunchRole.PROVIDER_ADMIN,
        profile=panel.SeatProfile(env={}),
        cwd=os.getcwd(),
    )

    assert result is marker
    assert Path(seat_keyring_exec.__file__).resolve() in checked


def test_native_fill_json_uses_private_atomic_writer(tmp_path, monkeypatch):
    writes = []
    monkeypatch.setattr(
        panel._seat_host_namespace,
        "write_private_atomic",
        lambda directory, name, data: writes.append((directory, name, data)),
    )
    target = tmp_path / "stream" / "president.pending.json"

    panel._write_json_atomically(target, {"schema": "fixture.v1", "ok": True})

    assert writes == [
        (
            target.parent,
            target.name,
            json.dumps({"schema": "fixture.v1", "ok": True}, indent=2, sort_keys=True).encode()
            + b"\n",
        )
    ]


def test_jailed_claude_subject_refusal_launches_nothing(tmp_path, monkeypatch):
    refusal = ExecutableDependencyError("authority_missing")
    monkeypatch.setattr(
        panel,
        "integrated_seat_subject",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(refusal),
    )
    monkeypatch.setattr(
        panel._seat_credentials,
        "resolve_claude_seat_credential",
        lambda *_args, **_kwargs: SimpleNamespace(
            token=b"synthetic-token", notices=[], source="login", expires_at=None
        ),
    )
    monkeypatch.setattr(
        panel,
        "launch_provider",
        lambda *_args, **_kwargs: pytest.fail("provider spawned after subject refusal"),
    )

    (tmp_path / "review" / panel._seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
    monkeypatch.setattr(panel._seat_jail, "tree_manifest_sha256_at", lambda _fd: "0" * 64)

    with pytest.raises(panel._seat_jail.SeatSandboxRefused) as caught:
        panel._prepare_jailed_claude(
            tmp_path / "review",
            tmp_path / "seat",
            SimpleNamespace(staged_tree_sha256="0" * 64),
            1,
            os.getpid(),
            ("artifact", "instructions"),
            transport="tui",
        )
    assert caught.value.code == panel._seat_jail.refused("jail_build")


@pytest.mark.parametrize("source", ["standalone", "managed_release"])
def test_jailed_gemini_admits_each_resolved_subject(tmp_path, monkeypatch, source):
    executable = tmp_path / "agy"
    executable.write_bytes(b"fixture agy")
    executable.chmod(0o700)
    admitted = []

    monkeypatch.setattr(
        panel,
        "integrated_seat_subject",
        lambda leg, _env: _subject(leg, source, executable),
    )
    monkeypatch.setattr(panel, "_approved_stage_or_refuse", lambda *_args: tmp_path / "tree")

    class Stop(RuntimeError):
        pass

    def admit(_env, *, subject_path=None, **_kwargs):
        admitted.append(subject_path)
        raise Stop

    monkeypatch.setattr(panel.gemini_heartbeat, "admit", admit)

    with pytest.raises(Stop):
        panel._prepare_jailed_gemini(
            tmp_path / "review",
            tmp_path / f"seat-{source}",
            SimpleNamespace(staged_tree_sha256="0" * 64),
            1,
            os.getpid(),
            ("artifact", "instructions"),
            SimpleNamespace(),
            env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
            credential="none",
        )
    assert admitted == [executable]


def test_jailed_gemini_admits_a_session_lease_subject(tmp_path, monkeypatch):
    fixture, dependencies = _install_gemini_dependency(tmp_path, monkeypatch)
    admitted = []
    monkeypatch.setattr(panel, "_approved_stage_or_refuse", lambda *_args: tmp_path / "tree")

    class Stop(RuntimeError):
        pass

    def admit(_env, *, subject_path=None, **_kwargs):
        admitted.append(subject_path)
        raise Stop

    monkeypatch.setattr(panel.gemini_heartbeat, "admit", admit)

    try:
        with pytest.raises(Stop):
            panel._prepare_jailed_gemini(
                tmp_path / "review",
                tmp_path / "seat-session",
                SimpleNamespace(staged_tree_sha256="0" * 64),
                1,
                os.getpid(),
                ("artifact", "instructions"),
                SimpleNamespace(),
                env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
                credential="none",
            )
        assert admitted == [fixture.subject]
    finally:
        _close_gemini_dependency(fixture, dependencies)


def test_invoke_board_requalifies_once_before_composition(tmp_path, monkeypatch):
    board = replace(
        DEFAULT_BOARD,
        seats=tuple(seat for seat in DEFAULT_BOARD.seats if seat.harness == "gemini"),
    )
    executable = tmp_path / "agy"
    executable.write_bytes(b"fixture agy")
    executable.chmod(0o700)
    events = []

    monkeypatch.setattr(
        panel,
        "integrated_seat_subject",
        lambda leg, _env: _subject(leg, "standalone", executable),
    )

    class Admission:
        def close(self):
            events.append("close")

    monkeypatch.setattr(
        agy_qualification,
        "requalify_once",
        lambda *_args, **kwargs: events.append(("requalify", kwargs["subject_path"]))
        or Admission(),
    )

    result = panel.invoke_board(
        board,
        "fixture",
        base_env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
        monitoring_policy="bounded",
        spawn=lambda *_args, **_kwargs: pytest.fail("direct spawn executed"),
    )

    assert events == [("requalify", executable), "close"]
    assert result.legs[0].status == "UNAVAILABLE"


def test_bounded_board_without_agy_returns_a_result(tmp_path):
    result = panel.invoke_board(
        DEFAULT_BOARD,
        "fixture",
        base_env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
        monitoring_policy="bounded",
        spawn=lambda *_args, **_kwargs: (1, "", "stub"),
    )
    assert len(result.legs) == len(DEFAULT_BOARD.seats)


def test_bounded_preflight_failure_refuses_only_the_gemini_leg(tmp_path, monkeypatch):
    executable = tmp_path / "agy"
    executable.write_bytes(b"fixture agy")
    executable.chmod(0o700)
    monkeypatch.setattr(
        panel,
        "integrated_seat_subject",
        lambda leg, _env: _subject(leg, "standalone", executable),
    )
    monkeypatch.setattr(
        agy_qualification,
        "requalify_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("agy_image_unqualified")
        ),
    )
    panel.board_preflight_requalify(
        DEFAULT_BOARD, {"HOME": str(tmp_path), "PATH": str(tmp_path)}
    )
    with pytest.raises(ValueError, match="agy_image_unqualified"):
        panel.board_preflight_requalify(
            DEFAULT_BOARD,
            {"HOME": str(tmp_path), "PATH": str(tmp_path)},
            heartbeat=True,
        )


def test_jailed_gemini_refuses_an_admission_without_a_path(tmp_path, monkeypatch):
    executable = tmp_path / "agy"
    executable.write_bytes(b"fixture agy")
    executable.chmod(0o700)
    monkeypatch.setattr(
        panel,
        "integrated_seat_subject",
        lambda leg, _env: _subject(leg, "standalone", executable),
    )
    monkeypatch.setattr(panel, "_approved_stage_or_refuse", lambda *_args: tmp_path / "tree")
    closed = []
    admission = SimpleNamespace(
        path=None,
        image=SimpleNamespace(sha256="f" * 64),
        admission_class="locally_qualified",
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(panel.gemini_heartbeat, "admit", lambda *_args, **_kwargs: admission)
    with pytest.raises(ValueError, match="gemini_heartbeat_capability_unavailable"):
        panel._prepare_jailed_gemini(
            tmp_path / "review",
            tmp_path / "seat-pathless",
            SimpleNamespace(staged_tree_sha256="0" * 64),
            1,
            os.getpid(),
            ("artifact", "instructions"),
            SimpleNamespace(),
            env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
            credential="none",
        )
    assert closed == [True]


def test_jailed_gemini_lease_requires_the_admitted_subject_digest(tmp_path, monkeypatch):
    fixture, dependencies = _install_gemini_dependency(tmp_path, monkeypatch)
    monkeypatch.setattr(panel, "_approved_stage_or_refuse", lambda *_args: tmp_path / "tree")
    closed = []
    admission = SimpleNamespace(
        path=fixture.subject,
        image=SimpleNamespace(sha256="b" * 64),
        admission_class="locally_qualified",
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(panel.gemini_heartbeat, "admit", lambda *_args, **_kwargs: admission)
    try:
        with pytest.raises(ValueError, match="gemini_heartbeat_capability_unavailable"):
            panel._prepare_jailed_gemini(
                tmp_path / "review",
                tmp_path / "seat-mismatched-lease",
                SimpleNamespace(staged_tree_sha256="0" * 64),
                1,
                os.getpid(),
                ("artifact", "instructions"),
                SimpleNamespace(),
                env={"HOME": str(tmp_path), "PATH": str(tmp_path)},
                credential="none",
            )
        assert closed == [True]
    finally:
        _close_gemini_dependency(fixture, dependencies)


def test_provider_lookups_use_only_absolute_path_entries(tmp_path, monkeypatch):
    work = tmp_path / "work"
    trusted = tmp_path / "trusted"
    work.mkdir()
    trusted.mkdir()
    for name in ("claude", "codex", "gemini"):
        for directory in (work, trusted):
            path = directory / name
            path.write_bytes(b"#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
    monkeypatch.chdir(work)
    env = {"PATH": os.pathsep.join((".", "", str(trusted)))}

    assert panel._resolve_claude_executable(env) == (trusted / "claude").resolve()
    for name in ("codex", "gemini"):
        _harness, source = panel._seat_provider_source(name, env)
        assert Path(source).resolve() == (trusted / name).resolve()
