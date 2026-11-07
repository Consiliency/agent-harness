"""TEAMHOST doctor rows, admission agreement and print-only LA-1 checklist."""

from __future__ import annotations

import ast
import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from phase_loop_runtime import doctor
from phase_loop_runtime import panel_invoker
from phase_loop_runtime import seat_admission
from phase_loop_runtime import seat_host_admin
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_jail_prerequisites as prerequisites
from phase_loop_runtime import seat_subject
from phase_loop_runtime.executable_dependency import ExecutableDependencyError


def _probes(value=True):
    return {name: (lambda value=value: value) for name in prerequisites.CHECKLIST_BY_NAME}


@pytest.mark.parametrize("missing", tuple(prerequisites.CHECKLIST_BY_NAME))
def test_each_prerequisite_row_uses_its_own_predicate_and_checklist(missing):
    probes = _probes()
    probes[missing] = lambda: False
    rows = prerequisites.check(deployment="source", predicates=probes, platform="linux")
    assert [row["name"] for row in rows if row["status"] == "missing"] == [missing]
    row = next(row for row in rows if row["name"] == missing)
    assert row["checklist"] == prerequisites.CHECKLIST_BY_NAME[missing]
    assert row["fix"].endswith(".") and "Also:" not in row["fix"]


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_off_linux_rows_are_unknown_without_running_a_predicate(platform):
    def forbidden():
        pytest.fail("off-Linux prerequisite predicate ran")

    rows = prerequisites.check(
        deployment="source",
        predicates={name: forbidden for name in prerequisites.CHECKLIST_BY_NAME},
        platform=platform,
    )
    assert all(
        row["status"] == "unknown" and row["reason"] == "platform_unsupported"
        for row in rows
    )


@pytest.mark.parametrize("deployment", ["managed", "uv_tool", "pip", "source", "unknown"])
def test_each_deployment_fix_is_one_sentence_and_managed_names_release(deployment):
    sentence = prerequisites.fix_sentence("pytest", deployment=deployment)
    assert sentence.endswith(".") and "Also:" not in sentence
    assert sentence.count("phase-loop seat-sandbox qualify") == 1
    assert ("LA1-RELEASE" in sentence) is (deployment == "managed")


def test_doctor_golden_and_closed_teamhost_rows_validate():
    package = files("phase_loop_runtime") / "schemas"
    schema = json.loads((package / "phase-loop-doctor.v1.schema.json").read_text())
    golden = json.loads((package / "phase-loop-doctor.v1.golden.json").read_text())
    jsonschema.validate(golden, schema)
    assert {row["name"] for row in golden["seat_jail_prerequisites"]} == set(
        prerequisites.CHECKLIST_BY_NAME
    )


def test_doctor_maps_registered_admission_verdicts(monkeypatch):
    monkeypatch.setattr(seat_admission, "registered_legs", lambda: ("claude", "gemini"))
    monkeypatch.setattr(
        seat_admission,
        "verdict",
        lambda leg, _env, execute=False: seat_admission.Verdict(
            leg,
            "refuses" if leg == "claude" else "unknown",
            code="claude_seat_token_missing" if leg == "claude" else None,
            reason=None if leg == "claude" else "launch_measurement",
        ),
    )
    assert doctor._seat_cli_qualification() == [
        {"leg": "claude", "status": "refuses", "code": "claude_seat_token_missing"},
        {"leg": "gemini", "status": "unknown", "reason": "launch_measurement"},
    ]


def _standalone(tmp_path: Path, leg: str) -> seat_subject.SeatSubject:
    path = tmp_path / leg
    path.write_bytes(b"fixture")
    path.chmod(0o700)
    return seat_subject.SeatSubject(leg, "standalone", path, None, None)


def test_admission_subject_refusal_is_the_integrated_launch_refusal(monkeypatch):
    refusal = ExecutableDependencyError("authority_missing")
    monkeypatch.setattr(
        seat_subject,
        "resolve_seat_subject",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(refusal),
    )
    with pytest.raises(ExecutableDependencyError) as launched:
        panel_invoker.integrated_seat_subject("claude", {"PATH": "/none"})
    doctor_verdict = seat_admission.verdict("claude", {"PATH": "/none"})
    assert launched.value.code == doctor_verdict.code == "authority_missing"
    assert doctor_verdict.status == "refuses"


@pytest.mark.parametrize(
    "host_code",
    [
        "seat_sandbox_unavailable_host",
        "seat_sandbox_unavailable_tiocsti",
        "seat_sandbox_unavailable_seat_uid",
    ],
)
def test_admission_reports_each_real_host_capability_code(tmp_path, monkeypatch, host_code):
    monkeypatch.setattr(
        seat_subject, "resolve_seat_subject", lambda leg, _env: _standalone(tmp_path, leg)
    )
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: host_code)
    outcome = seat_admission.verdict("claude", {"PATH": str(tmp_path)})
    assert (outcome.status, outcome.code) == ("refuses", host_code)


def test_admission_off_linux_runs_no_subject_or_provider(monkeypatch):
    monkeypatch.setattr(seat_admission.sys, "platform", "darwin")
    monkeypatch.setattr(
        seat_subject,
        "resolve_seat_subject",
        lambda *_args, **_kwargs: pytest.fail("off-Linux subject lookup ran"),
    )
    assert seat_admission.verdict("claude", {"PATH": "/spy"}) == seat_admission.Verdict(
        "claude", "unknown", reason="platform_unsupported"
    )


def test_print_only_admin_module_has_no_exec_import_and_is_not_runtime_imported(monkeypatch, capsys):
    source = Path(seat_host_admin.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported.isdisjoint({"subprocess", "pty"})
    assert not any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr.startswith(("exec", "spawn", "system"))
        for node in ast.walk(tree)
    )
    package = Path(seat_host_admin.__file__).parent
    for path in package.glob("*.py"):
        if path.name != "seat_host_admin.py":
            assert "import seat_host_admin" not in path.read_text(encoding="utf-8")
    monkeypatch.setenv("PATH", "/spy-executables")
    assert seat_host_admin.main(["--all"]) == 0
    output = capsys.readouterr().out
    assert all(item in output for item in seat_host_admin.ACTIONS)


def test_admin_json_prints_only_reported_missing_items(tmp_path, capsys):
    report = tmp_path / "doctor.json"
    report.write_text(
        json.dumps(
            {
                "seat_jail_prerequisites": [
                    {"name": "bwrap", "status": "missing", "checklist": "LA1-PACKAGES"},
                    {"name": "machine_id", "status": "present", "checklist": "LA1-MACHINE-ID"},
                ],
                "seat_cli_qualification": [
                    {"leg": "claude", "status": "refuses", "code": "authority_missing"}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert seat_host_admin.main([str(report)]) == 0
    output = capsys.readouterr().out
    assert "LA1-PACKAGES" in output and "LA1-AUTHORITY-PIN" in output
    assert "LA1-MACHINE-ID" not in output
