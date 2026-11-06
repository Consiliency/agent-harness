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
    from phase_loop_runtime import cli, seat_window as w, president_adapter as pa
    monkeypatch.setattr(w, "preflight", lambda: pytest.fail("owner gate must precede preflight"))
    monkeypatch.setattr(pa, "write_private_record", lambda *a, **k: pytest.fail("record written"))
    assert cli.main(["seat-window", "qualify", *(["--attended"] if attended else [])]) == 1
    assert "window_owner_approval_required" in capsys.readouterr().out


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
    monkeypatch.setattr(window, "owner_w1_approved", lambda: True)
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


def test_seats_firstseat_window_owner_gate_precedes_every_effect(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as window
    from phase_loop_runtime import president_adapter
    monkeypatch.setattr(window, "preflight", lambda: pytest.fail("preflight reached"))
    monkeypatch.setattr(window, "run_native_window", lambda **kwargs: pytest.fail("launch reached"))
    monkeypatch.setattr(president_adapter, "write_private_record",
                        lambda *args, **kwargs: pytest.fail("owner-disabled W1 wrote evidence"))
    assert window.qualify(window="W1", monitoring_policy="bounded", attended=True) == {
        "status": "candidate", "code": "window_owner_approval_required"}
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("help_lists_plugin", [True, False])
def test_seats_firstseat_window_i15_order_board_input_launch4_and_owner_counts(
    tmp_path, monkeypatch, help_lists_plugin,
):
    from dataclasses import dataclass
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker as panel, president_adapter
    from phase_loop_runtime import seat_jail_qualification as jailq
    from phase_loop_runtime import seat_window as window

    calls, writes = [], {}
    layouts = []

    def plant_layout(*, plugin_form):
        calls.append(("layout", plugin_form))
        value = SimpleNamespace(plugin_form=plugin_form, layout_sha256="1" * 64)
        layouts.append(value)
        return value

    def build_qualification_input(layout, base):
        calls.append(("build", layout.plugin_form))
        return SimpleNamespace(layout=layout, repo=base, commit="2" * 40)

    def launch(spec):
        calls.append(("launch", spec.kind, spec.qualification_input.layout.plugin_form))
        direct = SimpleNamespace(row="b_direct_without_proxy", outcome="refused", signature="fixture")
        stream = SimpleNamespace(outside_events=(), windows=(SimpleNamespace(
            events=(SimpleNamespace(decision="allow"), SimpleNamespace(decision="deny")),),))
        return SimpleNamespace(kind=spec.kind,
            help_lists_plugin=help_lists_plugin if spec.kind == "help" else None,
            stream=stream, bracket=SimpleNamespace(rows=(direct,)))

    def definition_probe(layout, controls):
        calls.append(("definition", tuple(item.kind for item in controls)))
        return SimpleNamespace(credentialed_control_required=True)

    board = SimpleNamespace(
        composition="admitted", board_outcome="terminated", canonical_gemini=True,
        staged_read=True, board_sha256="3" * 64, exec_record_sha256="4" * 64,
        tool_receipt_sha256="5" * 64, delivered_turn_sha256="6" * 64,
        leg_exec_records={name: (value * 64) for name, value in zip(
            ("claude", "gemini", "codex", "grok"), ("7", "8", "9", "a"), strict=True)},
        co_seats=("codex", "grok"),
        gemini=SimpleNamespace(input_sha256="a" * 64, watch=None,
            stream=SimpleNamespace(outside_events=(), windows=(SimpleNamespace(
                events=(SimpleNamespace(decision="allow"),)),),), binding=None),
    )

    def board_launch(spec):
        calls.append(("board", spec.qualification_input.layout.plugin_form,
                      spec.monitoring_policy))
        return board

    owner = SimpleNamespace(schema="seat_window_owner_summary.v1", context_id="placeholder",
        outcomes={name: "pass" if name in window.CONTAINMENT_FIELDS[:2] else "not_loaded"
                  for name in window.CONTAINMENT_FIELDS},
        unavailable_reasons={name: () for name in window.CONTAINMENT_FIELDS},
        undefined_surfaces=(), plugin_validation="valid" if help_lists_plugin else "not_listed",
        home_row_baseline="no_write_final",
        counted_lookups={"tree_control": 0, "runtime_control": 0,
                         "credentialed_tree_control": 0, "credentialed_runtime_control": 0},
        uncounted_home_lookups={"tree_control": 1, "runtime_control": 2,
                                "credentialed_tree_control": 3,
                                "credentialed_runtime_control": 4},
        voided_controls=(), expired_copy_control="pass", private_route=False)
    private = {"rows": {}, "canaries": [], "token_endpoint_events": {},
               "credential_events": {}, "lookups": {}, "home_row": {
                   "baseline": "1" * 64, "measured": "1" * 64},
               "manifest_differences": False, "delivered_copy_sha256": "2" * 64,
               "bracket": {}, "issuer": {}, "unavailable_reasons": {}}
    reduction = SimpleNamespace(
        containment={name: "pass" if name in window.CONTAINMENT_FIELDS[:2] else "not_loaded"
                     for name in window.CONTAINMENT_FIELDS},
        checks={name: True for name in window.CONTAINMENT_FIELDS},
        observation_sha256=window.digest(private),
        binding={
            "image_sha256": "b" * 64, "admission_class": "release_qualified",
            "help_sha256": "c" * 64, "stage_manifest_sha256": "d" * 64,
            "plant_layout_sha256": "1" * 64,
            "contract_sha256": window.CONTAINMENT_CONTRACT_SHA256,
            "control_argv_sha256": "f" * 64, "production_argv_sha256": "0" * 64,
            "control_input_sha256": "9" * 64, "measured_input_sha256": "8" * 64,
            "board_input_sha256": "a" * 64, "jail_profile_sha256": "7" * 64,
            "production_allowlist_sha256": "6" * 64,
            "refuse_all_allowlist_sha256": "5" * 64, "watch_sha256": "4" * 64,
            "proxy_sha256": "3" * 64, "validator_sha256": "2" * 64,
            "dependency_subject_sha256": None, "dependency_projection_sha256": None,
            "context_id": "placeholder", "account_label": "placeholder",
        },
        admitted=True,
        private=private,
        owner_summary=owner,
    )

    def reduce_containment(inputs):
        calls.append(("reduce", tuple(item.kind for item in inputs.controls),
                      inputs.board is board.gemini))
        reduction.binding["context_id"] = inputs.context.context_id
        reduction.binding["account_label"] = inputs.context.account_label
        owner.context_id = inputs.context.context_id
        return reduction

    @dataclass(frozen=True)
    class Spec:
        kind: str
        qualification_input: object
        model: str
        timeout_s: float

    @dataclass(frozen=True)
    class BoardSpec:
        qualification_input: object
        monitoring_policy: str

    monkeypatch.setattr(jailq, "plant_layout", plant_layout, raising=False)
    monkeypatch.setattr(jailq, "build_qualification_input", build_qualification_input,
                        raising=False)
    monkeypatch.setattr(jailq, "definition_probe", definition_probe, raising=False)
    monkeypatch.setattr(jailq, "ContextBinding", lambda **kw: SimpleNamespace(**kw), raising=False)
    monkeypatch.setattr(jailq, "ContainmentInputs", lambda **kw: SimpleNamespace(**kw), raising=False)
    monkeypatch.setattr(jailq, "reduce_containment", reduce_containment, raising=False)
    monkeypatch.setattr(panel, "WindowLaunchSpec", Spec, raising=False)
    monkeypatch.setattr(panel, "WindowBoardSpec", BoardSpec, raising=False)
    monkeypatch.setattr(panel, "window_control_launch", launch, raising=False)
    monkeypatch.setattr(panel, "window_board_launch", board_launch, raising=False)
    monkeypatch.setattr(window, "owner_w1_approved", lambda: True)
    monkeypatch.setattr(window, "preflight", lambda: SimpleNamespace(status="admitted"))
    monkeypatch.setattr(window.seat_jail, "execfind_pass_recorded", lambda _: True)
    monkeypatch.setattr(window.seat_egress_proxy, "unavailable_reason", lambda: None)
    monkeypatch.setattr(window, "_find_exec_source_attempt", lambda digest, root=None: "f" * 32)
    monkeypatch.setattr(window, "_host_digest", lambda: "0" * 64)
    monkeypatch.setattr(window, "account_isolation", lambda peer: True)
    monkeypatch.setattr(window, "_dependency_binding", lambda: (None, None))
    monkeypatch.setattr(window.sandbox_policy, "staging_root", lambda: tmp_path)

    def write(name, value, **kwargs):
        writes[name] = value
        return tmp_path / name

    monkeypatch.setattr(president_adapter, "write_private_record", write)
    result = window.qualify(window="W1", monitoring_policy="bounded", repo=tmp_path,
                            host_class="team", attended=True, peer_record="peer",
                            model="fixture-model")
    assert result == {"status": "candidate", "code": "window_review_required"}
    expected_prefix = [("layout", "nested"), ("build", "nested"),
                       ("launch", "help", "nested")]
    assert calls[:3] == expected_prefix
    if help_lists_plugin:
        assert calls[3] == ("launch", "plugin_validation", "nested")
        selected = "nested"
    else:
        assert calls[3] == ("layout", "plugin_json")
        selected = "plugin_json"
    launched = [item[1] for item in calls if item[0] == "launch"]
    assert launched == (["help"] + (["plugin_validation"] if help_lists_plugin else [])
                        + ["tree_control", "runtime_control",
                           "credentialed_tree_control", "credentialed_runtime_control",
                           "measured", "expired_copy"])
    assert launched.count("credentialed_tree_control") == 1
    assert launched.count("credentialed_runtime_control") == 1
    assert ("board", selected, "bounded") in calls
    assert calls[-1] == ("reduce", ("tree_control", "runtime_control",
                                    "credentialed_tree_control",
                                    "credentialed_runtime_control"), True)
    summary_name = next(name for name in writes if name.startswith("owner-summary-W1-"))
    assert writes[summary_name]["home_row_baseline"] == "no_write_final"
    assert writes[summary_name]["uncounted_home_lookups"] == {
        "tree_control": 1, "runtime_control": 2,
        "credentialed_tree_control": 3, "credentialed_runtime_control": 4}
    record = writes[next(name for name in writes if name.startswith("window-W1-"))]
    assert record["board_input_digest"] == "a" * 64
    assert record["delivered_turn_digest"] == "6" * 64
    assert record["containment"]["checks"] == reduction.checks


def test_seats_firstseat_window_board_composition_refusal_skips_reducer_and_writes(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker as panel, president_adapter
    from phase_loop_runtime import seat_jail_qualification as jailq
    from phase_loop_runtime import seat_window as window

    layout = SimpleNamespace(plugin_form="nested")
    qualification_input = SimpleNamespace(layout=layout)
    monkeypatch.setattr(jailq, "plant_layout", lambda **kwargs: layout, raising=False)
    monkeypatch.setattr(jailq, "build_qualification_input",
                        lambda *args: qualification_input, raising=False)
    monkeypatch.setattr(jailq, "definition_probe",
                        lambda *args: SimpleNamespace(credentialed_control_required=False),
                        raising=False)
    monkeypatch.setattr(jailq, "ContextBinding", lambda **kwargs: SimpleNamespace(**kwargs),
                        raising=False)
    monkeypatch.setattr(jailq, "ContainmentInputs", lambda **kwargs: SimpleNamespace(**kwargs),
                        raising=False)
    monkeypatch.setattr(jailq, "reduce_containment",
                        lambda inputs: pytest.fail("composition refusal reached reducer"),
                        raising=False)
    monkeypatch.setattr(panel, "WindowLaunchSpec", lambda **kwargs: SimpleNamespace(**kwargs),
                        raising=False)
    monkeypatch.setattr(panel, "WindowBoardSpec", lambda **kwargs: SimpleNamespace(**kwargs),
                        raising=False)
    monkeypatch.setattr(panel, "window_control_launch", lambda spec: SimpleNamespace(
        kind=spec.kind, help_lists_plugin=True), raising=False)
    monkeypatch.setattr(panel, "window_board_launch", lambda spec: SimpleNamespace(
        composition="refused"), raising=False)
    monkeypatch.setattr(window, "_dependency_binding", lambda: (None, None))
    monkeypatch.setattr(window.sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(president_adapter, "write_private_record",
                        lambda *args, **kwargs: pytest.fail("composition refusal wrote evidence"))

    assert window.run_native_window(repo=tmp_path, monitoring_policy="bounded",
                                    host_class="team") == {
        "status": "candidate", "code": "review_composition_refused"}
