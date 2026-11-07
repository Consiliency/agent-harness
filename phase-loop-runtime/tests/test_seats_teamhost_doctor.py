"""TEAMHOST doctor rows, admission agreement and print-only LA-1 checklist."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from phase_loop_runtime import agy_integrity
from phase_loop_runtime import agy_qualification
from phase_loop_runtime import claude_seat_transport
from phase_loop_runtime import doctor
from phase_loop_runtime import executable_dependency_startup
from phase_loop_runtime import panel_invoker
from phase_loop_runtime import seat_admission
from phase_loop_runtime import seat_egress_proxy
from phase_loop_runtime import seat_host_admin
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_jail_autoqualify
from phase_loop_runtime import seat_jail_prerequisites as prerequisites
from phase_loop_runtime import seat_subject
from phase_loop_runtime import seat_uid
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


@dataclass(frozen=True)
class AgreementRow:
    state: str
    leg: str
    status: str
    code: str | None = None
    reason: str | None = None


AGREEMENT_ROWS = (
    AgreementRow("release_agy", "gemini", "admits"),
    AgreementRow("valid_local_record", "gemini", "admits"),
    AgreementRow("mac_failed_record", "gemini", "refuses", "agy_image_unqualified"),
    AgreementRow("provenance_less_record", "gemini", "refuses", "agy_image_unqualified"),
    AgreementRow("no_record", "gemini", "refuses", "agy_image_unqualified"),
    AgreementRow("claude_credential_missing", "claude", "refuses", "claude_seat_token_missing"),
    AgreementRow("gemini_credential_missing", "gemini", "refuses", "gemini_seat_credential_missing"),
    AgreementRow("egress_uninstalled", "gemini", "refuses", "gemini_seat_egress_unavailable"),
    AgreementRow("authority_missing", "claude", "refuses", "authority_missing"),
    AgreementRow("authority_invalid", "claude", "refuses", "authority_invalid"),
    AgreementRow("guarded_frontdoor_failed", "claude", "refuses", "subject_mismatch"),
    AgreementRow("host_unavailable", "claude", "refuses", "seat_sandbox_unavailable_host"),
    AgreementRow(
        "host_unavailable_and_transport_invalid",
        "claude",
        "refuses",
        "seat_sandbox_unavailable_host",
    ),
    AgreementRow("tiocsti_unsafe", "claude", "refuses", "seat_sandbox_unavailable_tiocsti"),
    AgreementRow("seat_uid_unavailable", "claude", "refuses", "seat_sandbox_unavailable_seat_uid"),
    AgreementRow("pass_store_unsafe", "claude", "refuses", "seat_jail_qualification_failed"),
    AgreementRow("stale_jail_pass", "claude", "unknown", reason="launch_measurement"),
    AgreementRow("valid_jail_pass", "claude", "admits"),
    AgreementRow("transport_invalid", "claude", "refuses", claude_seat_transport.ROUTE_INVALID),
    AgreementRow("transport_not_admitted", "claude", "refuses", claude_seat_transport.NOT_ADMITTED),
    AgreementRow(
        "agy_capability_unavailable",
        "gemini",
        "refuses",
        "gemini_heartbeat_capability_unavailable",
    ),
)


PRELAUNCH_REFUSAL_CODES = frozenset(
    {
        "authority_missing",
        "authority_invalid",
        "subject_mismatch",
        claude_seat_transport.ROUTE_INVALID,
        claude_seat_transport.NOT_ADMITTED,
        "seat_sandbox_unavailable_host",
        "seat_sandbox_unavailable_tiocsti",
        "seat_sandbox_unavailable_seat_uid",
        "claude_seat_token_missing",
        "gemini_seat_credential_missing",
        "gemini_seat_egress_unavailable",
        "seat_jail_qualification_failed",
        "agy_image_unqualified",
        "gemini_heartbeat_capability_unavailable",
    }
)


def _configure_agreement_state(row, tmp_path, monkeypatch):
    executable = tmp_path / ("claude" if row.leg == "claude" else "agy")
    executable.write_bytes(b"fixture provider")
    executable.chmod(0o700)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    source = "managed_release" if row.state == "release_agy" else "standalone"

    def resolve(leg, _env):
        subject_codes = {
            "authority_missing": "authority_missing",
            "authority_invalid": "authority_invalid",
            "guarded_frontdoor_failed": "subject_mismatch",
        }
        if row.state in subject_codes:
            raise ExecutableDependencyError(subject_codes[row.state])
        return seat_subject.SeatSubject(
            leg,
            source,
            executable,
            "fixture-release" if source == "managed_release" else None,
            None,
        )

    monkeypatch.setattr(seat_subject, "resolve_seat_subject", resolve)
    monkeypatch.setattr(panel_invoker, "_PROVIDER_SEARCH_PATH", str(tmp_path))
    monkeypatch.setattr(seat_admission, "_profile_for", lambda _leg: None)
    transport_refusal = {
        "transport_invalid": claude_seat_transport.ROUTE_INVALID,
        "transport_not_admitted": claude_seat_transport.NOT_ADMITTED,
        "host_unavailable_and_transport_invalid": claude_seat_transport.ROUTE_INVALID,
    }.get(row.state)
    monkeypatch.setattr(
        claude_seat_transport,
        "resolve_jailed_claude_transport",
        lambda _env=None: (None, transport_refusal) if transport_refusal else ("tui", None),
    )
    host_code = {
        "host_unavailable": "seat_sandbox_unavailable_host",
        "host_unavailable_and_transport_invalid": "seat_sandbox_unavailable_host",
        "tiocsti_unsafe": "seat_sandbox_unavailable_tiocsti",
        "seat_uid_unavailable": "seat_sandbox_unavailable_seat_uid",
    }.get(row.state)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: host_code)
    monkeypatch.setattr(
        seat_jail,
        "_claude_credential_present",
        lambda: row.state != "claude_credential_missing",
    )
    monkeypatch.setattr(
        seat_jail,
        "gemini_operator_credential_present",
        lambda: row.state != "gemini_credential_missing",
    )
    egress_code = (
        "gemini_seat_egress_unavailable" if row.state == "egress_uninstalled" else None
    )
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: egress_code)
    monkeypatch.setattr(
        seat_egress_proxy,
        "unavailable_reason",
        lambda: "fixture unavailable" if egress_code else None,
    )
    monkeypatch.setattr(seat_jail, "jail_profile_digest", lambda _leg: "fixture-digest")
    pass_result = {
        "pass_store_unsafe": (False, "store_unsafe:mode"),
        "stale_jail_pass": (False, "layout_mismatch"),
    }.get(row.state, (True, "passed"))
    monkeypatch.setattr(seat_jail, "pass_record_verdict", lambda *_args, **_kwargs: pass_result)
    monkeypatch.setattr(
        seat_jail_autoqualify,
        "_default_qualify",
        lambda _leg: (_ for _ in ()).throw(RuntimeError("qualification must not run")),
    )

    agy_code = None
    if row.state in {"mac_failed_record", "provenance_less_record", "no_record"}:
        agy_code = "agy_image_unqualified"
    elif row.state == "agy_capability_unavailable":
        agy_code = "gemini_heartbeat_capability_unavailable"
    monkeypatch.setattr(
        agy_qualification,
        "admission_verdict",
        lambda *_args, **_kwargs: agy_qualification.AgyVerdict(
            "refuses" if agy_code else "admits", agy_code, None
        ),
    )

    def admit(_env, *, subject_path=None, **_kwargs):
        assert subject_path == executable
        if agy_code == "agy_image_unqualified":
            raise agy_integrity.AgyImageUnqualified(agy_code)
        if agy_code is not None:
            raise ValueError(agy_code)
        return SimpleNamespace(
            path=executable,
            image=SimpleNamespace(sha256="a" * 64),
            admission_class="release_qualified" if source == "managed_release" else "locally_qualified",
            close=lambda: None,
        )

    monkeypatch.setattr(panel_invoker.gemini_heartbeat, "admit", admit)
    monkeypatch.setattr(
        executable_dependency_startup, "current_dependency_for_provider", lambda _leg: None
    )
    monkeypatch.setattr(panel_invoker._seat_jail, "CLAUDE_PRESEED", {})
    monkeypatch.setattr(
        panel_invoker._seat_jail, "tree_manifest_sha256_at", lambda _fd: "0" * 64
    )
    monkeypatch.setattr(
        panel_invoker._seat_credentials,
        "resolve_claude_seat_credential",
        lambda *_args, **_kwargs: SimpleNamespace(
            token=b"synthetic-token", notices=[], source="login", expires_at=None
        ),
    )
    jail = lambda: SimpleNamespace(pass_fds=(), dependency_projection_digest=None)
    monkeypatch.setattr(
        panel_invoker, "_build_jail_with_owned_inputs", lambda *_args, **_kwargs: jail()
    )
    monkeypatch.setattr(
        panel_invoker, "_approved_stage_or_refuse", lambda review, _auth: review / "tree"
    )
    monkeypatch.setattr(panel_invoker, "_write_gemini_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(panel_invoker, "_write_egress_ca", lambda seat, _ca: seat / "ca.crt")
    return executable


def _real_seat_preparation(row, tmp_path):
    env = {"HOME": str(tmp_path), "PATH": str(tmp_path)}
    try:
        panel_invoker.integrated_seat_subject(row.leg, env)
    except ExecutableDependencyError as exc:
        return seat_admission.Verdict(row.leg, "refuses", code=exc.code)
    route, _notices, refusal = panel_invoker._seat_route_for_spawn(
        row.leg,
        SimpleNamespace(staged_tree_sha256="0" * 64, instructions_sha256=None),
        eligible=True,
        decide=lambda leg, **kw: seat_jail.decide_seat_route(
            leg,
            capable=seat_jail.seat_sandbox_capable,
            claude_token_present=seat_jail._claude_credential_present,
            gemini_credential_present=seat_jail.gemini_operator_credential_present,
            gemini_egress_unavailable=seat_egress_proxy.unavailable_reason,
            **kw,
        ),
    )
    if refusal is not None:
        return seat_admission.Verdict(row.leg, "refuses", code=refusal)

    if row.leg == "claude":
        _transport, refusal = claude_seat_transport.resolve_jailed_claude_transport(env)
        if refusal is not None:
            return seat_admission.Verdict(row.leg, "refuses", code=refusal)

    review = tmp_path / f"review-{row.state}"
    (review / panel_invoker._seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
    auth = SimpleNamespace(staged_tree_sha256="0" * 64)
    try:
        if row.leg == "claude":
            panel_invoker._prepare_jailed_claude(
                review,
                tmp_path / f"seat-{row.state}",
                auth,
                1,
                1,
                ("artifact", "instructions"),
                transport="tui",
            )
        else:
            panel_invoker._prepare_jailed_gemini(
                review,
                tmp_path / f"seat-{row.state}",
                auth,
                1,
                1,
                ("artifact", "instructions"),
                SimpleNamespace(ca_cert=tmp_path / "ca.crt", proxy_url="http://fixture"),
                env=env,
                credential="none",
            )
    except agy_integrity.AgyImageUnqualified:
        return seat_admission.Verdict(row.leg, "refuses", code="agy_image_unqualified")
    except ExecutableDependencyError as exc:
        return seat_admission.Verdict(row.leg, "refuses", code=exc.code)
    except seat_jail.SeatSandboxRefused as exc:
        return seat_admission.Verdict(row.leg, "refuses", code=exc.code)
    except ValueError as exc:
        return seat_admission.Verdict(row.leg, "refuses", code=str(exc))
    return seat_admission.Verdict(row.leg, "admits")


def _agreement_holds(doctor_verdict, launch_verdict):
    if doctor_verdict.status == "admits":
        return launch_verdict.status == "admits"
    if doctor_verdict.status == "refuses":
        return (
            launch_verdict.status == "refuses"
            and launch_verdict.code == doctor_verdict.code
        )
    return True


@pytest.mark.parametrize("row", AGREEMENT_ROWS, ids=lambda row: row.state)
def test_doctor_and_seat_preparation_agree(row, tmp_path, monkeypatch):
    _configure_agreement_state(row, tmp_path, monkeypatch)
    env = {"HOME": str(tmp_path), "PATH": str(tmp_path)}
    doctor_verdict = seat_admission.verdict(row.leg, env, execute=True)
    launch_verdict = _real_seat_preparation(row, tmp_path)
    assert (doctor_verdict.status, doctor_verdict.code, doctor_verdict.reason) == (
        row.status,
        row.code,
        row.reason,
    )
    assert _agreement_holds(doctor_verdict, launch_verdict)


def test_agreement_rows_cover_every_prelaunch_code():
    covered = {row.code for row in AGREEMENT_ROWS if row.status == "refuses"}
    assert covered == PRELAUNCH_REFUSAL_CODES


@pytest.mark.parametrize("state", ["mac_failed_record", "provenance_less_record"])
def test_record_existence_mutant_breaks_agreement(state, tmp_path, monkeypatch):
    row = next(row for row in AGREEMENT_ROWS if row.state == state)
    _configure_agreement_state(row, tmp_path, monkeypatch)
    monkeypatch.setattr(agy_qualification, "has_record", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        agy_qualification,
        "admission_verdict",
        lambda env, subject_path, *, execute: agy_qualification.AgyVerdict(
            "admits" if agy_qualification.has_record("fixture") else "refuses",
            None,
            None,
        ),
    )
    doctor_verdict = seat_admission.verdict(
        row.leg, {"HOME": str(tmp_path), "PATH": str(tmp_path)}, execute=True
    )
    launch_verdict = _real_seat_preparation(row, tmp_path)
    assert doctor_verdict.status == "admits"
    assert launch_verdict == seat_admission.Verdict(
        row.leg, "refuses", code="agy_image_unqualified"
    )
    assert not _agreement_holds(doctor_verdict, launch_verdict)


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


def test_admission_uses_the_real_claude_transport_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        seat_subject, "resolve_seat_subject", lambda leg, _env: _standalone(tmp_path, leg)
    )
    monkeypatch.setattr(seat_admission, "_profile_for", lambda _leg: None)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    monkeypatch.setattr(seat_jail, "_claude_credential_present", lambda: True)
    monkeypatch.setattr(seat_jail, "jail_profile_digest", lambda _leg: "d")
    monkeypatch.setattr(
        seat_jail, "pass_record_verdict", lambda *_args, **_kwargs: (True, "passed")
    )
    env = {
        "PATH": str(tmp_path),
        claude_seat_transport.ROUTE_ENV: "not-a-transport",
    }
    outcome = seat_admission.verdict("claude", env, execute=True)
    assert (outcome.status, outcome.code) == (
        "refuses",
        claude_seat_transport.ROUTE_INVALID,
    )


@pytest.mark.parametrize(
    "predicate",
    [
        "profile_credential",
        "profile_precondition",
        "claude_credential",
        "gemini_credential",
    ],
)
def test_admission_inventory_predicate_failures_are_guarded(
    predicate, tmp_path, monkeypatch
):
    leg = "gemini" if predicate == "gemini_credential" else "claude"
    monkeypatch.setattr(
        seat_subject, "resolve_seat_subject", lambda selected, _env: _standalone(tmp_path, selected)
    )
    monkeypatch.setattr(
        claude_seat_transport,
        "resolve_jailed_claude_transport",
        lambda _env=None: ("tui", None),
    )
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)

    def explode():
        raise OSError("fixture inventory failure")

    if predicate.startswith("profile_"):
        profile = SimpleNamespace(
            recorded_stop=None,
            credential_present=(explode if predicate == "profile_credential" else lambda: True),
            credential_missing_code="claude_seat_token_missing",
            preconditions=(
                SimpleNamespace(
                    check=(explode if predicate == "profile_precondition" else lambda: None)
                ),
            ),
            allowlist_id=None,
        )
        monkeypatch.setattr(seat_admission, "_profile_for", lambda _leg: profile)
    else:
        monkeypatch.setattr(seat_admission, "_profile_for", lambda _leg: None)
        monkeypatch.setattr(
            seat_jail,
            "_claude_credential_present",
            explode if predicate == "claude_credential" else lambda: True,
        )
        monkeypatch.setattr(
            seat_jail,
            "gemini_operator_credential_present",
            explode if predicate == "gemini_credential" else lambda: True,
        )

    assert seat_admission.verdict(leg, {"PATH": str(tmp_path)}, execute=True) == (
        seat_admission.Verdict(leg, "unknown", reason="inventory_failed")
    )


def test_uid_map_helper_and_non_root_rows_use_the_route_predicates(monkeypatch):
    monkeypatch.setattr(
        seat_uid,
        "_privileged_helper",
        lambda path: path == seat_uid.NEWUIDMAP,
    )
    monkeypatch.setattr(prerequisites.os, "geteuid", lambda: 0)
    probes = prerequisites._predicates()
    assert probes["uid_map_helpers"]() is False
    assert probes["non_root_operator"]() is False

    monkeypatch.setattr(seat_uid, "_privileged_helper", lambda _path: True)
    monkeypatch.setattr(prerequisites.os, "geteuid", lambda: 1000)
    probes = prerequisites._predicates()
    assert probes["uid_map_helpers"]() is True
    assert probes["non_root_operator"]() is True


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


def test_print_only_admin_module_has_no_exec_import_and_is_not_runtime_imported(
    tmp_path, monkeypatch, capsys
):
    source = Path(seat_host_admin.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            if node.module == "os":
                assert not any(
                    alias.name.startswith(("exec", "spawn", "system"))
                    for alias in node.names
                )
    assert imported.isdisjoint({"subprocess", "pty"})
    assert not any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr.startswith(("exec", "spawn", "system"))
        for node in ast.walk(tree)
    )
    package = Path(seat_host_admin.__file__).parent
    for path in package.rglob("*.py"):
        if path.name == "seat_host_admin.py":
            continue
        imported_tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(imported_tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.endswith("seat_host_admin") for alias in node.names
                ), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").endswith("seat_host_admin"), path
                assert all(alias.name != "seat_host_admin" for alias in node.names), path

    spies, calls = tmp_path / "spy", tmp_path / "calls"
    spies.mkdir()
    for name in (
        "bwrap",
        "setpriv",
        "nsenter",
        "sysctl",
        "newuidmap",
        "newgidmap",
        "unshare",
        "iptables",
        "slirp4netns",
        "getent",
        "python3",
        "sh",
    ):
        spy = spies / name
        spy.write_text(f"#!/bin/sh\necho {name} >> {calls}\n", encoding="utf-8")
        spy.chmod(0o700)
    monkeypatch.setenv("PATH", str(spies))
    assert seat_host_admin.main(["--all"]) == 0
    output = capsys.readouterr().out
    assert all(item in output for item in seat_host_admin.ACTIONS)
    assert not calls.exists()

    report = tmp_path / "doctor.json"
    report.write_text(
        json.dumps(
            {
                "seat_jail_prerequisites": [
                    {
                        "name": "bwrap",
                        "status": "missing",
                        "checklist": "LA1-PACKAGES",
                    }
                ],
                "seat_cli_qualification": [],
            }
        ),
        encoding="utf-8",
    )
    assert seat_host_admin.main([str(report)]) == 0
    assert "LA1-PACKAGES" in capsys.readouterr().out
    assert not calls.exists()


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
