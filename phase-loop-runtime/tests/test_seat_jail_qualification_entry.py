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


def test_seats_firstseat_window_cli(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli, seat_window as window
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    called = []
    monkeypatch.setattr(window, "qualify", lambda **kw: called.append(kw) or {"status": "candidate"})
    assert cli.main(["seat-window", "qualify", "--window", "W1", "--monitoring-policy", "bounded"]) == 1
    assert called[0]["window"] == "W1"
    assert called[0]["monitoring_policy"] == "bounded"
    assert "candidate" in capsys.readouterr().out


@pytest.mark.parametrize("attended", [False, True])
def test_seats_firstseat_window_real_cli(tmp_path, monkeypatch, capsys, attended):
    from types import SimpleNamespace
    from phase_loop_runtime import cli, seat_window as w, president_adapter as pa
    monkeypatch.setattr(w, "preflight", lambda: SimpleNamespace(status="admitted"))
    monkeypatch.setattr(w.seat_jail, "execfind_pass_recorded", lambda *a: True)
    monkeypatch.setattr(w.seat_egress_proxy, "unavailable_reason", lambda: None)
    monkeypatch.setattr(pa, "write_private_record", lambda *a, **k: pytest.fail("record written"))
    assert cli.main(["seat-window", "qualify", *(["--attended"] if attended else [])]) == 1
    assert ("window_supplier_unavailable" if attended else "window_attendance_required") in capsys.readouterr().out


def test_seats_firstseat_window_candidates_and_preflight(monkeypatch):
    from phase_loop_runtime import seat_window as window
    rows = window.readiness_rows()
    assert {r["vendor"] for r in rows if r["kind"] == "vendor"} == {"claude", "gemini", "codex", "grok", "pi"}
    assert len([r for r in rows if r["kind"] == "remote"]) == 5
    assert all(r["status"] == "candidate" for r in window.candidates(rows, "team"))
    seen = []
    def available(vendor):
        seen.append(("available", vendor))
        return vendor != "grok"
    def auth(vendor):
        seen.append(("auth", vendor))
        return True
    outcome = window.preflight(is_available=available, auth_ok=auth)
    assert len(seen) == 8
    assert outcome.status == "policy_refused" and outcome.unmet_slots


def test_seats_firstseat_window_refusal_launches_nothing(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as window
    from phase_loop_runtime.advisor_board.composition import CompositionOutcome
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(window, "preflight", lambda **kw: CompositionOutcome("policy_refused", "review_composition_refused", ("grok",), "restore subscription login"))
    monkeypatch.setattr(window, "run_native_window", lambda **kw: pytest.fail("must not launch"))
    result = window.qualify(window="W1", monitoring_policy="bounded")
    assert result == {"status": "candidate", "code": "review_composition_refused"}
    assert not list(tmp_path.rglob("*.json"))


def test_seats_firstseat_window_probe_cli(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli, panel_invoker as pi
    calls = []
    monkeypatch.setattr(pi, "probe_grok_tools", lambda command, **kw: calls.append((command, kw)) or {"passed": False})
    assert cli.main(["seat-window", "probe-tools", "--vendor", "grok"]) == 1
    assert len(calls) == 5
    assert isinstance(calls[0][1]["allowed_tools"], set)
    import json
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "candidate"
    assert {r["route"] for r in result["routes"]} == {"execute", "workflow", "review", "sealed", "staged"}


def test_seats_firstseat_window_probe_launch_forms(tmp_path, monkeypatch, capsys):
    import json
    import subprocess
    from phase_loop_runtime import cli, panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    def runner(argv, **kw):
        if argv[-1] == "--help":
            text = "--list-tools Print tool definitions without running a model"
        elif argv[-1] == "--version":
            text = "fixture-v1"
        else:
            assert "--reasoning-effort" in argv
            text = json.dumps({"tools": sorted(pi._grok_allowed_tools(argv)) if "--tools" in argv else ["write"],
                               "diagnostics": []})
        return subprocess.CompletedProcess(argv, 0, text, "")
    monkeypatch.setattr(pi, "run_provider", runner)
    assert cli.main(["seat-window", "probe-tools"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert all(route["passed"] for route in result["routes"])
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (True, ""))
    launched = []
    def run(command, **kw):
        launched.append(command)
        return pi._LegRun(0, "AGREE", "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    for brokered in (False, True):
        output = tmp_path / str(brokered)
        output.mkdir()
        assert pi._exec_leg("grok", tmp_path, output, artifact="fixture",
            **({"broker_prompt": "fixture", "broker_evidence": {}} if brokered else {}))[:2] == (0, "AGREE")
    assert len(launched) == 2


def test_seats_firstseat_window_row_observations():
    from phase_loop_runtime import panel_invoker as pi, seat_window as w
    rows = w.candidates(w.readiness_rows(), "team")
    leg = pi.PanelLegResult("gemini", "OK", "AGREE")
    object.__setattr__(leg, "_leg_exec_metadata", {"record_digest": "e" * 64})
    observations = w.candidate_observations(rows, [leg])
    assert {r["id"] for r in observations} == {r["id"] for r in rows}
    assert next(r for r in observations if r["id"] == "vendor:gemini") == {
        "id": "vendor:gemini", "outcome": "observed", "exec_record_digest": "e" * 64}
    # A vendor leg supplies no evidence for a president route or another vendor.
    assert all(r["outcome"] == "unavailable" and r["exec_record_digest"] is None
               for r in observations if r["id"] != "vendor:gemini")


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


NONCANONICAL_INFORMATIONAL_ARGV = [
    ["--hel"],
    ["--ver"],
    ["-hh"],
    ["--help", "--help"],
    ["-h", "--help"],
    ["--version", "--version"],
]


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


def test_seats_firstseat_window_managed_cli(monkeypatch, capsys):
    from phase_loop_runtime import seat_window as window
    session, dependency = _session(monkeypatch)
    entered = []
    def qualify(**kwargs):
        assert current_dependency_for_provider("synthetic") is dependency
        entered.append(kwargs)
        return {"status": "candidate"}
    monkeypatch.setattr(window, "qualify", qualify)
    try:
        assert session.run_cli(["seat-window", "qualify", "--window", "W1",
                                "--monitoring-policy", "bounded"]) == 1
        assert len(entered) == 1 and entered[0]["window"] == "W1"
        assert '"candidate"' in capsys.readouterr().out
        assert not session._tasks
    finally:
        session.close()


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
    monkeypatch.setattr(qualification.subprocess, "Popen", reject("provider process"))


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
    assert "expected no arguments or exactly one of" in capsys.readouterr().err
    assert effects == []


@pytest.mark.parametrize("argv", NONCANONICAL_INFORMATIONAL_ARGV)
def test_direct_main_refuses_noncanonical_informational_argv_before_effects(
    monkeypatch,
    capsys,
    argv: list[str],
) -> None:
    effects: list[str] = []
    _reject_effect_boundaries(monkeypatch, effects)
    monkeypatch.setattr(sys, "argv", ["phase-loop-seat-jail-qualification", *argv])

    with pytest.raises(SystemExit) as refused:
        qualification.main()

    assert refused.value.code == 2
    assert "expected no arguments or exactly one of" in capsys.readouterr().err
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


@pytest.mark.parametrize("argv", NONCANONICAL_INFORMATIONAL_ARGV)
def test_managed_noncanonical_informational_argv_refuses_and_releases_lease(
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
        assert "expected no arguments or exactly one of" in capsys.readouterr().err
        assert dependency.revalidations == 1
        assert startup._CURRENT_TASK.get() is None
        assert not startup._ACTIVE_REQUIRED
        assert not session._tasks
        assert effects == []
    finally:
        session.close()
    assert session.closed
    assert dependency.closed


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


def test_seats_firstseat_window_supplier_pending(monkeypatch):
    from types import SimpleNamespace
    from phase_loop_runtime import seat_window as window
    monkeypatch.setattr(window, "preflight", lambda: SimpleNamespace(status="admitted"))
    monkeypatch.setattr(window.seat_jail, "execfind_pass_recorded", lambda _: True)
    monkeypatch.setattr(window.seat_egress_proxy, "unavailable_reason", lambda: None)
    from phase_loop_runtime import president_adapter
    monkeypatch.setattr(president_adapter, "write_private_record",
                        lambda *args: pytest.fail("pending supplier must not write evidence"))
    assert window.qualify(window="W1", monitoring_policy="bounded", attended=True) == {
        "status": "candidate", "code": "window_supplier_unavailable"}
