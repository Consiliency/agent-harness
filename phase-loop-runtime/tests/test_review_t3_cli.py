"""Standalone CLI conformance; every command runs in a fresh Python process.

Only local BAML worker operations run. Fake host observations are input files,
never provider calls or evidence of route qualification.
"""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from phase_loop_runtime import review_gateway as g
from phase_loop_runtime import review_t3 as t
from test_review_contract import payload, raw
from test_review_t3 import capabilities, delivery, observation


ROOT = Path(__file__).resolve().parents[2]
MARKER = "PRIVATE brief café 🐈 with unresolved objection"


def audited_cli():
    """Additional side-effect control around the actual standalone CLI main.

    Ordinary roundtrip tests use unwrapped ``python -m``. This control denies
    network/process effects except the real local worker. It never mocks a
    parser, its reply, or acceptance.
    """
    import runpy
    import socket
    from phase_loop_runtime import baml_modular as b
    worker_path = str(Path(b.__file__).with_name("_baml_worker.py"))
    audit_path = Path(os.environ["RT3_TEST_AUDIT"])
    def audit(event, args):
        if event == "subprocess.Popen":
            argv = args[1]
            assert argv[:4] == [sys.executable, "-I", "-S", worker_path], "unexpected process side effect"
            with audit_path.open("a") as stream:
                stream.write("local_baml_worker\n")
        elif event == "socket.connect":
            assert args[0].family == socket.AF_UNIX, "unexpected network side effect"
        elif event in {"os.system", "os.exec", "os.posix_spawn"}:
            raise AssertionError("unexpected dispatch side effect")
    sys.addaudithook(audit)
    runpy.run_module("phase_loop_runtime.cli", run_name="__main__")


def unavailable_coordinator_cli():
    """Exercise sqlite3.connect's operational exception in a standalone process."""
    import runpy
    def audit(event, args):
        if event == "sqlite3.connect" and Path(args[0]).name == "reviews.sqlite3":
            raise sqlite3.OperationalError("PRIVATE local open failure")
    sys.addaudithook(audit)
    runpy.run_module("phase_loop_runtime.cli", run_name="__main__")


@pytest.fixture
def cli(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    state = tmp_path / "state"
    scope = {"parent_thread_id": "parent", "checkout": str(checkout)}
    inputs = {"charter": {"schema": "t3_host_charter.v1", "review_brief": MARKER,
                         "host_scope": scope, "allow_correction": True},
              "coordinator_key": "cli/seat", "seat": "reviewer",
              "subjects": [{"kind": "document", "sha256": "b" * 64,
                            "paths": ["contract.md"], "revision": None}]}
    return {"state": state, "scope": scope, "inputs": inputs, "tmp": tmp_path, "calls": []}


def private_file(cli, value):
    path = cli["tmp"] / f"input-{len(list(cli['tmp'].glob('input-*')))}.json"
    path.write_bytes(t.relay_json(value))
    path.chmod(0o600)
    return path


def command(cli, operation, binding=None, value=None, *, path=None, extra=(), env=None):
    argv = [sys.executable, "-m", "phase_loop_runtime.cli", "typed-review", operation,
            "--state", str(cli["state"]), "--parent-thread", cli["scope"]["parent_thread_id"],
            "--checkout", cli["scope"]["checkout"]]
    if binding:
        argv += ["--binding", binding]
    if value is not None:
        path = private_file(cli, value)
    if path is not None:
        argv += ["--input", str(path)]
    argv += list(extra)
    if cli.get("audit"):
        argv[1:3] = ["-c", "from test_review_t3_cli import audited_cli; audited_cli()"]
    if cli.get("connect_failure"):
        argv[1:3] = ["-c", "from test_review_t3_cli import unavailable_coordinator_cli; unavailable_coordinator_cli()"]
    child_env = {**os.environ, "PYTHONPATH": f"{ROOT}/phase-loop-runtime/src:{ROOT}/phase-loop-runtime/tests",
                 "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    if cli.get("audit"):
        child_env["RT3_TEST_AUDIT"] = str(cli["tmp"] / "side-effects.log")
    proc = subprocess.run(argv, cwd=ROOT, env=child_env, capture_output=True, text=True, timeout=60)
    cli["calls"].append({"argv": argv, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    (cli["tmp"] / "commands.json").write_text(json.dumps(cli["calls"], indent=2))
    assert MARKER not in proc.stdout + proc.stderr
    return proc


def success(proc):
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    result = json.loads(proc.stdout)
    assert result["schema"] == "t3_cli_result.v1" and result["ok"] is True
    return result


def refused(proc, code=None):
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stderr == ""
    result = json.loads(proc.stdout)
    assert set(result) == {"schema", "ok", "rejection_code"}
    assert result["schema"] == "t3_cli_result.v1" and result["ok"] is False
    if code:
        assert result["rejection_code"] == code
    return result


def service(cli):
    return g.T3ReviewService(cli["state"], host_scope=cli["scope"])


def begin(cli):
    requested = success(command(cli, "request", value=cli["inputs"]))
    binding = requested["request_binding"]
    metadata = success(command(cli, "prepare", binding, {"target": {"providerInstanceId": "provider", "model": "model"},
                                                        "capabilities": capabilities()}))
    action = json.loads((cli["state"] / metadata["private_action_file"]).read_bytes())
    return binding, action, metadata


def register(cli, binding, action):
    req = service(cli).coordinator.load_request(binding)
    status = {"taskId": "task-" + req.attempt_id, "childThreadId": "thread-" + req.attempt_id,
              "childRunId": "run-" + req.attempt_id, "providerInstanceId": "provider", "model": "model",
              "status": "completed", "workState": "result_available", "summary": "PRIVATE-SUMMARY"}
    wrapper = {"schema": t.REGISTRATION_VERSION, "request_binding": binding,
               "client_request_id": action["arguments"]["clientRequestId"], "payload_digest": action["payload_digest"],
               "host_scope": cli["scope"], "observation": observation("delegate_task", action["arguments"], status)}
    success(command(cli, "register", binding, wrapper))
    return req, status, wrapper


@pytest.mark.parametrize("correction", [False, True])
def test_standalone_roundtrip_and_exact_saved_prompts(cli, correction):
    binding, action, metadata = begin(cli)
    assert metadata["kind"] == "dispatch" and metadata["redispatch_capable"] is False
    assert "arguments" not in metadata
    assert action["arguments"]["task"].encode() == service(cli).coordinator.build_request(binding).prompt.encode()
    assert set(action["arguments"]) == {"task", "target", "mode", "role", "isolation", "interactionMode", "clientRequestId"}
    assert action["arguments"]["isolation"] == "shared"
    # A later process cannot renew an offered original action.
    assert success(command(cli, "resume", binding))["kind"] == "unresolved"
    req, status, _ = register(cli, binding, action)
    assert success(command(cli, "resume", binding))["kind"] == "recover"
    original_body = b"PRIVATE invalid original\n" if correction else raw(payload(req))
    package = delivery(service(cli), req, status, original_body)
    original = success(command(cli, "intake", binding, package))
    if correction:
        assert original["rejection_code"] == "invalid_json" and not original["usable"]
        metadata = success(command(cli, "correction", binding, {"capabilities": capabilities()}))
        fixed = service(cli).coordinator.correction_request(binding)
        corrected_action = json.loads((cli["state"] / metadata["private_action_file"]).read_bytes())
        assert corrected_action["arguments"]["task"].encode() == service(cli).coordinator.build_request(fixed.binding).prompt.encode()
        assert corrected_action["arguments"]["clientRequestId"] != action["arguments"]["clientRequestId"]
        assert base64.b64encode(original_body).decode() in corrected_action["arguments"]["task"]
        assert service(cli).coordinator.correction_context(fixed.binding)["original_body"] == original_body
        assert "substantive_replacement" in corrected_action["arguments"]["task"]
        assert success(command(cli, "correction", binding, {"capabilities": capabilities()}))["kind"] == "unresolved"
        req, status, _ = register(cli, fixed.binding, corrected_action)
        package = delivery(service(cli), req, status, raw(payload(req)))
        record = success(command(cli, "intake", fixed.binding, package))
        assert record["replaces_record_id"] == original["record_id"]
        assert record["lineage_id"] == original["lineage_id"]
        refused(command(cli, "correction", binding, {"capabilities": capabilities()}), "result_unavailable")
        refused(command(cli, "correction", fixed.binding, {"capabilities": capabilities()}), "result_unavailable")
        binding = fixed.binding
    else:
        record = original
    assert record["content_valid"] and record["usable"] and not record["governed_eligible"]
    assert record["provenance"] == "HOST_ATTESTED" and record["operation"] == "parse_review_reply"
    assert record["ipc_id"] is not None and record["runtime_version"] == "0.20.1"
    again = success(command(cli, "resume", binding))
    assert again["record_id"] == record["record_id"]
    assert "PRIVATE-SUMMARY" not in json.dumps(cli["calls"])
    assert "Inspected café" not in json.dumps(cli["calls"], ensure_ascii=False)
    assert cli["state"].stat().st_mode & 0o777 == 0o700
    for path in cli["state"].iterdir():
        assert path.stat().st_mode & 0o077 == 0, path.name
    with sqlite3.connect(service(cli).coordinator.path) as db:
        history = db.execute("SELECT COUNT(*) FROM validations").fetchone()[0]
        assert history >= 2  # Fresh-process resume actually revalidates locally.


@pytest.mark.parametrize("fault", ["missing", "schema", "blank", "scope", "permission", "extra", "changed"])
def test_charter_and_immutable_request(cli, fault):
    inputs = deepcopy(cli["inputs"])
    if fault == "changed":
        first = success(command(cli, "request", value=inputs))
        inputs["charter"]["review_brief"] += " changed"
        refused(command(cli, "request", value=inputs), "delivery_conflict")
        assert success(command(cli, "request", value=cli["inputs"]))["request_binding"] == first["request_binding"]
        return
    if fault == "missing":
        inputs.pop("charter")
    elif fault == "schema":
        inputs["charter"]["schema"] = "unknown"
    elif fault == "blank":
        inputs["charter"]["review_brief"] = " "
    elif fault == "scope":
        inputs["charter"]["host_scope"]["parent_thread_id"] = "other"
    elif fault == "permission":
        inputs["charter"]["allow_correction"] = "true"
    else:
        inputs["charter"]["policy"] = "GOVERNED"
    refused(command(cli, "request", value=inputs))
    with sqlite3.connect(service(cli).coordinator.path) as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


@pytest.mark.parametrize("operation", ["prepare", "register", "intake", "resume", "correction"])
def test_unbound_operations_refuse(cli, operation):
    refused(command(cli, operation, "0" * 64, {} if operation != "resume" else None))


@pytest.mark.parametrize("override", ["policy", "eligibility", "governed_provenance", "provenance", "source_snapshot", "redispatch_capable"])
def test_request_json_cannot_confer_authority(cli, override):
    inputs = {**cli["inputs"], override: "GOVERNED"}
    refused(command(cli, "request", value=inputs), "binding_mismatch")


def test_environment_and_resume_json_cannot_upgrade_or_redispatch(cli):
    binding, _, _ = begin(cli)
    result = success(command(cli, "resume", binding, {"redispatch_capable": True, "eligibility": "GOVERNED"},
        env={"T3_REDISPATCH_CAPABLE": "true", "REDISPATCH_CAPABLE": "true", "T3_REVIEW_POLICY": "GOVERNED"}))
    assert result["kind"] == "unresolved" and result["redispatch_capable"] is False
    assert json.loads((cli["state"] / result["private_action_file"]).read_bytes())["arguments"] == {}


@pytest.mark.parametrize("fault", ["public", "symlink", "duplicate", "invalid_utf8", "nan", "array"])
def test_private_input_files(cli, fault):
    path = private_file(cli, cli["inputs"])
    if fault == "public":
        path.chmod(0o644)
    elif fault == "symlink":
        alias = cli["tmp"] / "alias.json"
        alias.symlink_to(path)
        path = alias
    elif fault == "duplicate":
        path.write_text('{"charter":1,"charter":2}')
    elif fault == "invalid_utf8":
        path.write_bytes(b"\xffPRIVATE")
    elif fault == "nan":
        path.write_text('{"charter":NaN}')
    else:
        path.write_text('[]')
    refused(command(cli, "request", path=path))
    assert not cli["state"].exists()


@pytest.mark.parametrize("via_symlink", [False, True])
def test_state_placement(cli, via_symlink):
    checkout = Path(cli["scope"]["checkout"])
    base = checkout
    if via_symlink:
        base = cli["tmp"] / "alias"
        base.symlink_to(checkout, target_is_directory=True)
    cli["state"] = base / "private"
    refused(command(cli, "request", value=cli["inputs"]), "binding_mismatch")
    assert not (checkout / "private").exists()


@pytest.mark.parametrize("changed", ["parent", "checkout"])
def test_state_scope_cannot_change(cli, changed):
    binding, _, _ = begin(cli)
    if changed == "parent":
        cli["scope"]["parent_thread_id"] = "other"
    else:
        other = cli["tmp"] / "other-checkout"
        other.mkdir()
        cli["scope"]["checkout"] = str(other)
    refused(command(cli, "resume", binding), "binding_mismatch")


def test_same_uid_is_a_trust_assumption(cli):
    binding, _, metadata = begin(cli)
    # Owner-only files remain readable to the same UID; no authentication or
    # reviewer isolation is inferred from checkout placement or file modes.
    path = cli["state"] / metadata["private_action_file"]
    assert path.stat().st_uid == os.getuid() and os.access(path, os.R_OK | os.W_OK)
    assert g.read_private_json(path)["arguments"]["task"]
    assert success(command(cli, "resume", binding))["kind"] == "unresolved"


def test_changed_same_key_payload_and_late_registration(cli):
    binding, action, _ = begin(cli)
    catalog = capabilities()
    catalog["providers"][0]["models"].append({"id": "different", "options": []})
    refused(command(cli, "prepare", binding, {"target": {"providerInstanceId": "provider", "model": "different"},
                                             "capabilities": catalog}), "delivery_conflict")
    req, status, wrapper = register(cli, binding, action)
    wrapper["observation"] = observation("task_status", {"taskId": status["taskId"]}, status)
    success(command(cli, "register", binding, wrapper))
    resumed = success(command(cli, "resume", binding))
    assert resumed["kind"] == "recover"
    assert json.loads((cli["state"] / resumed["private_action_file"]).read_bytes())["arguments"] == {"taskId": status["taskId"]}
    wrapper["observation"]["result"]["childRunId"] = "different"
    refused(command(cli, "register", req.binding, wrapper), "delivery_conflict")


def test_cli_first_status_registration_of_unresolved_intent(cli):
    binding, action, _ = begin(cli)
    assert success(command(cli, "resume", binding))["kind"] == "unresolved"
    req = service(cli).coordinator.load_request(binding)
    status = {"taskId": "task", "childThreadId": "thread", "childRunId": "run",
              "providerInstanceId": "provider", "model": "model", "status": "completed", "workState": "result_available"}
    wrapper = {"schema": t.REGISTRATION_VERSION, "request_binding": binding, "host_scope": cli["scope"],
               "client_request_id": action["arguments"]["clientRequestId"], "payload_digest": action["payload_digest"],
               "observation": observation("task_status", {"taskId": status["taskId"]}, status)}
    with sqlite3.connect(service(cli).path) as db:
        assert db.execute("SELECT registration FROM intents").fetchone()[0] is None
    first = success(command(cli, "register", binding, wrapper))
    assert success(command(cli, "register", binding, wrapper)) == first
    assert success(command(cli, "resume", binding))["kind"] == "recover"
    assert success(command(cli, "intake", binding, delivery(service(cli), req, status, raw(payload(req)))))["usable"]


@pytest.mark.parametrize("field", ["model", "childRunId", "childThreadId", "taskId"])
def test_registration_missing_identity(cli, field):
    binding, action, _ = begin(cli)
    status = {"taskId": "task", "childThreadId": "thread", "childRunId": "run", "providerInstanceId": "provider", "model": "model"}
    status[field] = None
    wrapper = {"schema": t.REGISTRATION_VERSION, "request_binding": binding, "host_scope": cli["scope"],
               "client_request_id": action["arguments"]["clientRequestId"], "payload_digest": action["payload_digest"],
               "observation": observation("delegate_task", action["arguments"], status)}
    refused(command(cli, "register", binding, wrapper), "binding_mismatch")
    assert success(command(cli, "resume", binding))["kind"] == "unresolved"


def test_private_action_existing_artifact_is_not_dispatch_authority(cli):
    binding, action, metadata = begin(cli)
    path = cli["state"] / metadata["private_action_file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() in path.name
    assert action["request_binding"] == binding
    assert success(command(cli, "resume", binding))["kind"] == "unresolved"


def test_cli_host_actions_have_only_local_worker_side_effects(cli):
    cli["audit"] = True
    binding, action, _ = begin(cli)
    req, status, _ = register(cli, binding, action)
    result = success(command(cli, "intake", binding, delivery(service(cli), req, status, b"invalid")))
    assert result["rejection_code"] == "invalid_json"
    fixed_action = success(command(cli, "correction", binding, {"capabilities": capabilities()}))
    fixed_binding = fixed_action["request_binding"]
    private = json.loads((cli["state"] / fixed_action["private_action_file"]).read_bytes())
    req, status, _ = register(cli, fixed_binding, private)
    accepted = success(command(cli, "intake", fixed_binding, delivery(service(cli), req, status, raw(payload(req)))))
    assert accepted["usable"] and accepted["operation"] == "parse_review_reply"
    assert success(command(cli, "resume", fixed_binding))["record_id"] == accepted["record_id"]
    effects = (cli["tmp"] / "side-effects.log").read_text().splitlines()
    assert len(effects) >= 4 and set(effects) == {"local_baml_worker"}


def test_cli_unsupported_capability_precedes_intent(cli):
    binding = success(command(cli, "request", value=cli["inputs"]))["request_binding"]
    unavailable = capabilities()
    unavailable["features"]["incrementalThreadRead"] = False
    refused(command(cli, "prepare", binding, {"target": {"providerInstanceId": "provider", "model": "model"},
                                              "capabilities": unavailable}), "result_unavailable")
    with sqlite3.connect(service(cli).path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("change", ["provider", "model", "options"])
def test_cli_correction_prepare_target_binding(cli, monkeypatch, existing, change):
    from test_review_t3_faults import alternate_target, option_target, crash
    target, catalog = option_target()
    binding = success(command(cli, "request", value=cli["inputs"]))["request_binding"]
    meta = success(command(cli, "prepare", binding, {"target": target, "capabilities": catalog}))
    action = json.loads((cli["state"] / meta["private_action_file"]).read_bytes())
    req, status, _ = register(cli, binding, action)
    success(command(cli, "intake", binding, delivery(service(cli), req, status, b"invalid")))
    if existing:
        saved = success(command(cli, "correction", binding, {"capabilities": catalog}))
    else:
        local = service(cli)
        with monkeypatch.context() as patch:
            patch.setattr(local, "prepare", crash)
            with pytest.raises(SystemExit):
                local.correction(binding, capabilities=catalog)
    reserved = service(cli).coordinator.correction_request(binding)
    exports = set(cli["state"].glob("action-*.json"))
    changed, fresh = alternate_target(target, catalog, change)
    refused(command(cli, "prepare", reserved.binding, {"target": changed, "capabilities": fresh}), "binding_mismatch")
    assert set(cli["state"].glob("action-*.json")) == exports
    with sqlite3.connect(service(cli).path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents WHERE binding=?", (reserved.binding,)).fetchone()[0] == int(existing)
    assert service(cli).coordinator.correction_request(binding).binding == reserved.binding
    recovered = success(command(cli, "prepare", reserved.binding, {"target": target, "capabilities": catalog}))
    assert recovered["kind"] == ("unresolved" if existing else "dispatch")
    if existing:
        assert recovered["payload_digest"] == saved["payload_digest"]
    else:
        exported = json.loads((cli["state"] / recovered["private_action_file"]).read_bytes())
        assert exported["arguments"]["target"] == target
    assert success(command(cli, "correction", binding, {"capabilities": catalog}))["kind"] == "unresolved"


@pytest.mark.parametrize("choices", ["hi", ["hi"], None, {}, [None], [{}], [{"id": ""}], [{"id": 1}]])
def test_cli_malformed_select_options(cli, choices):
    from test_review_t3_faults import option_target
    binding = success(command(cli, "request", value=cli["inputs"]))["request_binding"]
    target, catalog = option_target()
    catalog["providers"][0]["models"][0]["options"][0]["options"] = choices
    refused(command(cli, "prepare", binding, {"target": target, "capabilities": catalog}), "result_unavailable")
    assert not list(cli["state"].glob("action-*.json"))
    with sqlite3.connect(service(cli).path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


def test_cli_local_coordinator_open_failure_is_metadata_only(cli):
    cli["connect_failure"] = True
    proc = command(cli, "request", value=cli["inputs"])
    refused(proc, "result_unavailable")
    assert "PRIVATE" not in proc.stdout + proc.stderr
    assert not list(cli["state"].glob("action-*.json"))


@pytest.mark.parametrize("exception", [RuntimeError, SystemExit, KeyboardInterrupt])
def test_cli_residual_exception_boundary(cli, monkeypatch, capsys, exception):
    from types import SimpleNamespace
    def fail(*args, **kwargs):
        raise exception("PRIVATE ordinary failure")
    monkeypatch.setattr(g, "T3ReviewService", fail)
    args = SimpleNamespace(input=None, state=str(cli["state"]), parent_thread="parent", checkout=cli["scope"]["checkout"])
    if exception is RuntimeError:
        assert g.cli_main(args) == 1
        output = capsys.readouterr()
        assert json.loads(output.out) == {"schema": "t3_cli_result.v1", "ok": False, "rejection_code": "result_unavailable"}
        assert output.err == ""
    else:
        with pytest.raises(exception):
            g.cli_main(args)


@pytest.mark.parametrize("reserved", [False, True])
def test_cli_runtime_mode_change_preserves_correction_budget(cli, monkeypatch, reserved):
    from test_review_t3_faults import crash
    binding, action, _ = begin(cli)
    req, status, _ = register(cli, binding, action)
    success(command(cli, "intake", binding, delivery(service(cli), req, status, b"invalid")))
    if reserved:
        local = service(cli)
        with monkeypatch.context() as patch:
            patch.setattr(local, "prepare", crash)
            with pytest.raises(SystemExit):
                local.correction(binding, capabilities=capabilities())
    correction = service(cli).coordinator.correction_request(binding)
    changed = {**capabilities(), "runtimeMode": "approval-required"}
    exports = set(cli["state"].glob("action-*.json"))
    refused(command(cli, "prepare", binding, {"target": action["arguments"]["target"], "capabilities": changed}), "binding_mismatch")
    refused(command(cli, "correction", binding, {"capabilities": changed}), "binding_mismatch")
    if reserved:
        refused(command(cli, "prepare", correction.binding, {"target": action["arguments"]["target"], "capabilities": changed}), "binding_mismatch")
        assert service(cli).coordinator.correction_request(binding).binding == correction.binding
    else:
        assert service(cli).coordinator.correction_request(binding) is None
    assert set(cli["state"].glob("action-*.json")) == exports
    with sqlite3.connect(service(cli).path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 1
    recovered = success(command(cli, "correction", binding, {"capabilities": capabilities()}))
    assert recovered["kind"] == "dispatch"
    if reserved:
        assert recovered["request_binding"] == correction.binding


def test_cli_refused_intake_is_metadata_only(cli):
    binding, action, _ = begin(cli)
    req, status, _ = register(cli, binding, action)
    package = delivery(service(cli), req, status, b"PRIVATE-MODEL-BODY")
    package["terminal"]["profile"] = "PRIVATE-DIAGNOSTIC"
    proc = command(cli, "intake", binding, package)
    refused(proc, "result_unavailable")
    assert "PRIVATE" not in proc.stdout + proc.stderr


@pytest.mark.parametrize("operation", ["request", "prepare", "register", "intake", "resume", "correction"])
def test_cli_help_grammar(cli, operation):
    proc = command(cli, operation, extra=("--help",))
    assert proc.returncode == 0 and proc.stderr == ""
    for name in ("--state", "--parent-thread", "--checkout", "--input"):
        assert name in proc.stdout
    assert ("--binding" in proc.stdout) == (operation != "request")
    assert "--policy" not in proc.stdout and "--redispatch" not in proc.stdout
