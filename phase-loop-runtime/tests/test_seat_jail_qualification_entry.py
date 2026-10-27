from __future__ import annotations

import sys

import pytest

from phase_loop_runtime import executable_dependency_startup as startup
from phase_loop_runtime import seat_jail_qualification as qualification
from phase_loop_runtime.executable_dependency_startup import (
    DependencyStartupSession,
    QualifiedRuntimePackage,
    current_dependency_for_provider,
)


class FakeDependency:
    provider = "synthetic"
    projection_digest = "7" * 64

    def __init__(self) -> None:
        self.closed = False
        self.revalidations = 0
        self.validated_providers: list[str] = []

    def revalidate(self) -> None:
        self.revalidations += 1

    def validate_provider(self, provider: str) -> None:
        assert provider == self.provider
        self.validated_providers.append(provider)

    def close(self) -> None:
        self.closed = True


class QualificationBoundaryReached(RuntimeError):
    pass


def _runtime_package() -> QualifiedRuntimePackage:
    return QualifiedRuntimePackage(
        distribution="phase-loop-runtime",
        version="0.7.27",
        install_root="/synthetic/runtime",
        install_root_device=1,
        install_root_inode=2,
        installed_tree_manifest_id="1" * 64,
        installed_tree_files_sha256="2" * 64,
        distribution_metadata_sha256="3" * 64,
        distribution_record_path="phase_loop_runtime.dist-info/RECORD",
        distribution_record_sha256="4" * 64,
        python_executable="/synthetic/python",
        python_executable_device=1,
        python_executable_inode=3,
        python_executable_size=1,
        python_executable_sha256="5" * 64,
        private_runtime_binding_sha256="6" * 64,
    )


def _session(monkeypatch) -> tuple[DependencyStartupSession, FakeDependency]:
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda _package: None)
    dependency = FakeDependency()
    return DependencyStartupSession(
        runtime_package=_runtime_package(),
        dependency=dependency,  # type: ignore[arg-type]
    ), dependency


def _reject_effect_boundaries(monkeypatch, effects: list[str]) -> None:
    def reject(name: str):
        def blocked(*_args, **_kwargs):
            effects.append(name)
            raise AssertionError(f"effect boundary reached: {name}")

        return blocked

    monkeypatch.setattr(qualification, "qualify", reject("qualify"))
    monkeypatch.setattr(qualification, "_record_pass", reject("qualification write"))
    monkeypatch.setattr(qualification, "_write_private", reject("qualification file write"))
    monkeypatch.setattr(qualification, "_run_probe_in_jail", reject("qualification probe"))
    monkeypatch.setattr(qualification.subprocess, "run", reject("provider process"))


@pytest.mark.parametrize("argv", [["-h"], ["--help"], ["--version"]])
def test_managed_help_and_version_are_effect_free_provider_free_commands(
    monkeypatch,
    capsys,
    argv: list[str],
) -> None:
    session, dependency = _session(monkeypatch)
    effects: list[str] = []
    _reject_effect_boundaries(monkeypatch, effects)
    try:
        assert session.run_seat_jail_qualification(argv) == 0
        output = capsys.readouterr()
        assert output.err == ""
        if argv == ["--version"]:
            assert output.out == "phase-loop-seat-jail-qualification 0.7.27\n"
        else:
            assert "usage: phase-loop-seat-jail-qualification" in output.out
        assert dependency.revalidations == 0
        assert not session._tasks
        assert effects == []
    finally:
        session.close()


def test_direct_main_uses_actual_sys_argv_without_help_bypass(monkeypatch, capsys) -> None:
    effects: list[str] = []
    _reject_effect_boundaries(monkeypatch, effects)
    monkeypatch.setattr(sys, "argv", ["phase-loop-seat-jail-qualification", "--help"])
    assert qualification.main() == 0
    assert "usage: phase-loop-seat-jail-qualification" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["phase-loop-seat-jail-qualification", "--help", "unexpected"],
    )
    with pytest.raises(SystemExit) as refused:
        qualification.main()
    assert refused.value.code == 2
    assert "unrecognized arguments: unexpected" in capsys.readouterr().err
    assert effects == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--help", "unexpected"],
        ["unexpected", "--version"],
        ["--help", "--version"],
        ["--unknown"],
    ],
)
def test_mixed_and_unknown_arguments_refuse_under_required_lease(
    monkeypatch,
    capsys,
    argv: list[str],
) -> None:
    session, dependency = _session(monkeypatch)
    effects: list[str] = []
    _reject_effect_boundaries(monkeypatch, effects)
    try:
        assert qualification.qualification_provider_capable(argv)
        with pytest.raises(SystemExit) as refused:
            session.run_seat_jail_qualification(argv)
        assert refused.value.code == 2
        assert capsys.readouterr().err.startswith("usage: phase-loop-seat-jail-qualification")
        assert dependency.revalidations == 1
        assert not session._tasks
        assert effects == []
    finally:
        session.close()


def test_no_argument_qualification_reaches_effect_boundary_with_required_lease(monkeypatch) -> None:
    session, dependency = _session(monkeypatch)
    lower_effects: list[str] = []

    def qualification_boundary() -> dict[str, object]:
        assert current_dependency_for_provider("synthetic") is dependency
        raise QualificationBoundaryReached

    monkeypatch.setattr(qualification, "qualify", qualification_boundary)
    rejecting_boundaries = {
        "_record_pass": "qualification write",
        "_write_private": "qualification file write",
        "_run_probe_in_jail": "qualification probe",
    }

    def reject(label: str):
        def blocked(*_args, **_kwargs):
            lower_effects.append(label)
            raise AssertionError(f"effect boundary reached: {label}")

        return blocked

    for name, label in rejecting_boundaries.items():
        monkeypatch.setattr(qualification, name, reject(label))

    monkeypatch.setattr(qualification.subprocess, "run", reject("provider process"))
    try:
        assert qualification.qualification_provider_capable([])
        with pytest.raises(QualificationBoundaryReached):
            session.run_seat_jail_qualification([])
        assert dependency.revalidations == 1
        assert dependency.validated_providers == ["synthetic"]
        assert not session._tasks
        assert lower_effects == []
    finally:
        session.close()
