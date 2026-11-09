"""Real isolated Python children, synthetic operator files, no provider processes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime import supervised_launch_binding as binding
from test_supervised_launch import case as _case, qualify

case = _case


INPUTS = ["binding", "validator", "codec", "qualification", "template", "config"]


def binding_files(case):
    qualification = qualify(case)
    root = case.root / "operator"
    validator = root / "validator.py"
    validator.write_text('import json\nfrom phase_loop_runtime.supervised_launch import Admit\n'
                         'def validate(view):\n    return Admit(view.launch_digest, view.envelope["attempt_id"])\n')
    codec = root / "codec.py"
    codec.write_text('import json\nimport hashlib\ndef decode(capture):\n'
                     '    return capture.envelope, capture.raw_digest\n')
    paths = {"validator": validator, "codec": codec, "qualification": qualification,
             "config": case.config.config_path, "template": case.config.template_path}
    manifest = root / "binding.json"
    manifest.write_text(json.dumps({key: str(value) for key, value in paths.items()}))
    paths["binding"] = manifest
    return paths


def child(case, paths, *, mutation=None, wrong_owner=None, load_only=True):
    source_root = Path(__file__).resolve().parents[1] / "src"
    tests_root = Path(__file__).resolve().parent
    shadow = case.root / "workspace"
    for name in ("json.py", "hashlib.py", "phase_loop_runtime.py", "validator.py", "codec.py"):
        (shadow / name).write_text('raise RuntimeError("ambient shadow entered")\n')
    code = f'''
import sys
from pathlib import Path
sys.path.insert(0, {str(source_root)!r})
import phase_loop_runtime
resolved = Path(phase_loop_runtime.__file__).resolve()
assert resolved.is_relative_to(Path({str(source_root)!r}).resolve()), resolved
print("checkout_module=" + str(resolved), flush=True)
from phase_loop_runtime import supervised_launch as launch
from phase_loop_runtime import supervised_launch_binding as binding
paths = { {key: str(value) for key, value in paths.items()}!r}
'''
    if mutation:
        code += f'''
sys.path.insert(0, {str(tests_root)!r})
from test_supervised_launch_mutations import mutant
import pytest
patch = pytest.MonkeyPatch()
control = {mutation!r}
if control in ("trusted_uid", "trusted_mode"):
    changed = mutant(patch, launch, control)
    binding.trusted_bytes = changed.trusted_bytes
else:
    binding = mutant(patch, binding, control)
'''
    if wrong_owner:
        code += f'''
import os
from types import SimpleNamespace
victim = Path({str(wrong_owner)!r}).stat().st_ino
original_stat = os.fstat
def wrong_stat(fd):
    info = original_stat(fd)
    if info.st_ino == victim:
        values = {{name: getattr(info, name) for name in dir(info) if name.startswith("st_")}}
        values["st_uid"] = os.getuid() + 1
        return SimpleNamespace(**values)
    return info
os.fstat = wrong_stat
'''
    code += f'''
import json
result = binding.load_validator_binding(Path(paths["binding"]), workspace=Path({str(shadow)!r}), target=Path({str(case.root / 'target')!r}))
if isinstance(result, binding.Refused):
    print(json.dumps({{"reason": result.reason}}))
elif {load_only!r}:
    print(json.dumps({{"reason": None, "binding_digest": result.binding_digest}}))
else:
    raw = {json.dumps(case.envelope).encode()!r}
    prepared = launch.prepare_launch(raw, validator=result.validator, decoder=result.decoder, config=result.config)
    if isinstance(prepared, launch.Refused):
        print(json.dumps({{"reason": prepared.reason}}))
    else:
        assert isinstance(launch.consume_admission(prepared), launch.LaunchInputs)
        print(json.dumps({{"reason": None, "binding_digest": result.binding_digest}}))
'''
    env = dict(os.environ, PYTHONPATH=str(shadow), SUPERVISED_VALIDATOR="validator")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=shadow, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    lines = result.stdout.splitlines()
    assert lines[0].startswith("checkout_module=")
    assert Path(lines[0].split("=", 1)[1]).is_relative_to(source_root)
    print(lines[0])
    return json.loads(lines[-1])


def test_binding_isolated_absolute_and_transitive_shadowing(case):
    paths = binding_files(case)
    assert child(case, paths, load_only=False)["reason"] is None


@pytest.mark.parametrize("kind", INPUTS)
@pytest.mark.parametrize("unsafe", ["group", "world", "symlink", "owner"])
def test_binding_trusted_inputs(case, kind, unsafe):
    paths = binding_files(case)
    victim = paths[kind]
    owner = None
    if unsafe in {"group", "world"}:
        victim.chmod(0o620 if unsafe == "group" else 0o602)
    elif unsafe == "symlink":
        data = victim.read_bytes()
        victim.unlink()
        other = victim.with_suffix(".real")
        other.write_bytes(data)
        victim.symlink_to(other)
    else:
        owner = victim
    assert child(case, paths, wrong_owner=owner)["reason"] is not None


@pytest.mark.parametrize("kind", INPUTS)
@pytest.mark.parametrize("control", ["trusted_mode", "trusted_uid"])
def test_binding_uid_mode_mutations(case, kind, control):
    paths = binding_files(case)
    victim = paths[kind]
    owner = victim if control == "trusted_uid" else None
    if control == "trusted_mode":
        victim.chmod(0o620)
    assert child(case, paths, wrong_owner=owner)["reason"] is not None
    # Guard removal must make the *same* rejection assertion fail after import.
    with pytest.raises(AssertionError):
        assert child(case, paths, mutation=control, wrong_owner=owner)["reason"] is not None


def test_binding_trusted_import_mutation(case):
    paths = binding_files(case)
    assert child(case, paths)["reason"] is None
    # Mutation changes absolute-byte loading to ambient import; cwd/PYTHONPATH
    # remain excluded by -I, so the positive resolution witness goes red.
    with pytest.raises(AssertionError):
        assert child(case, paths, mutation="trusted_import")["reason"] is None


def test_binding_absent_and_unisolated(case):
    assert binding.load_validator_binding(None, workspace=case.root / "workspace",
                                          target=case.root / "target") == binding.Refused("isolated_python_required")
    paths = binding_files(case)
    paths["binding"].unlink()
    assert child(case, paths)["reason"] is not None


def test_binding_workspace_location(case):
    paths = binding_files(case)
    path = case.root / "workspace/binding.json"
    path.write_bytes(paths["binding"].read_bytes())
    paths["binding"] = path
    assert child(case, paths)["reason"] == "untrusted_location"


def test_external_binding_non_admit(case):
    paths = binding_files(case)
    paths["validator"].write_text('def validate(view):\n    return True\n')
    assert child(case, paths, load_only=False)["reason"] == "admit_required"


@pytest.mark.parametrize("kind", ["validator", "codec"])
@pytest.mark.parametrize("error", ["SystemExit", "KeyboardInterrupt"])
def test_binding_callback_refusal(case, kind, error):
    paths = binding_files(case)
    paths[kind].write_text(f"raise {error}()\n")
    assert child(case, paths)["reason"] == "binding_invalid"


def test_managed_binding_uses_password_database(tmp_path, monkeypatch):
    import importlib
    from types import SimpleNamespace
    original = binding.MANAGED_BINDING
    with monkeypatch.context() as patch:
        patch.setenv("HOME", str(tmp_path / "env-home"))
        patch.setenv("XDG_STATE_HOME", str(tmp_path / "env-state"))
        patch.setenv("XDG_CONFIG_HOME", str(tmp_path / "env-config"))
        patch.setattr(binding.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path / "operator")))
        importlib.reload(binding)
        assert binding.MANAGED_BINDING == tmp_path / "operator/.local/state/phase-loop/supervised-launch-binding.json"
        assert not binding.MANAGED_BINDING.exists()
    importlib.reload(binding)
    assert binding.MANAGED_BINDING == original


@pytest.fixture
def v2_operator(case, monkeypatch):
    from types import SimpleNamespace
    from phase_loop_runtime.supervised_contracts import V2_INPUT_ARTIFACT_SHA256
    from phase_loop_runtime.supervised_launch import AttemptBinding
    root = case.root / "operator"
    def write(name, value):
        path = root / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path
    marker = root / "activation-marker"
    codec = root / "public_codec.py"
    codec.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("activated")\n'
                     'from phase_loop_runtime.supervised_envelope_v2 import *\n')
    validator = root / "public_validator.py"
    validator.write_text('from phase_loop_runtime.supervised_launch import Admit\n'
                         'def validate(view): return Admit(view.launch_digest, "attempt-1")\n')
    authority = "a" * 64
    context = dict(expected_assignment_digest=authority, expected_snapshot_ref="b" * 64,
        expected_crosswalk_ref="c" * 64, timeout_max_seconds=60, qualified_routes=[], policy_epoch="epoch-1",
        revoked_record_ids=[], caller_context_suitability={}, policy={"issuer_records": {}, "time_basis": "system_utc"})
    context_path = write("v2-context.json", context)
    settings = dict(case.settings, declared_roots={"refs": str(case.root / "references")},
                    worker_audit_entry_cap=1000, worker_audit_byte_cap=1048576)
    case.config.config_path.write_text(json.dumps(settings))
    qualification_path = root / "v2-qualification.txt"
    qualification_path.write_text("synthetic qualification only")
    environment_path = write("v2-environment.json", {"classification": {"LANG": "non_secret", "PHASE_LOOP_SCRATCH_DECIDED": "non_secret"}})
    template_path = write("v2-template.json", {"argv": [str(case.executable)], "helpers": [],
                                               "spawn_cwd": {"namespace": "workspace", "path": "."}})
    spec = {"slots": {"workspace": "root", "target": "root", "reference_roots": "roots"},
            "launch": {"workspace": {"slot": "workspace"}, "target": {"slot": "target"},
                       "reference_roots": {"slot": "reference_roots"}, "argv": [str(case.executable)],
                       "cwd": {"slot": "workspace"}, "cwd_locator": {"namespace": "workspace", "path": "."},
                       "instructions": {"source": None, "content": "synthetic instructions"},
                       "references": [{"role": "baseline", "source": {"namespace": "declared_root", "root": "refs", "path": "baseline"},
                                       "path": str(case.root / "references/baseline")}],
                       "executable_chain": [{"wire": {"role": "executable", "locator_kind": "declared", "locator": "synthetic"}, "path": str(case.executable)}],
                       "config_path": str(case.config.config_path), "template_path": str(template_path),
                       "qualification_path": str(qualification_path), "environment_policy_path": str(environment_path),
                       "environment_policy_id": "fixture", "non_secret_environment": {"LANG": "C.UTF-8", "PHASE_LOOP_SCRATCH_DECIDED": "frozen_capture"},
                       "secret_sources": [], "timeout_seconds": 30, "deadline_action": "terminate_process_group",
                       "tier": "post_write_audit_only", "base_commit": None, "target_map": [],
                       "declared_roots": {"refs": str(case.root / "references")}}}
    spec_path = write("v2-spec.json", spec)
    controllers = root / "controllers"
    controllers.mkdir(mode=0o700)
    document = dict(schema="agent-harness.supervised-launch-binding.v2", controller_root=str(controllers),
        context=str(context_path), spec=str(spec_path), input_seal=V2_INPUT_ARTIFACT_SHA256,
        context_slots=["expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref"],
        implementations={kind: {"path": str(path), "sha256": binding.sha256(path.read_bytes())}
                         for kind, path in (("codec", codec), ("validator", validator))})
    path = write("v2-binding.json", document)
    roots = dict(workspace=case.root / "workspace", target=case.root / "target",
                 reference_roots=(case.root / "references",))
    controller_context = {key: value for key, value in context.items() if key != "policy"}
    controller = dict(h="d" * 64, attempt=dict(assignment_digest=authority, run_id="run-1", attempt_id="attempt-1"),
                      context=controller_context, slots={"workspace": str(roots["workspace"]), "target": str(roots["target"]),
                                                        "reference_roots": [str(roots["reference_roots"][0])]})
    monkeypatch.setattr(binding, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True), modules=sys.modules))
    return SimpleNamespace(path=path, document=document, context=context, context_path=context_path,
                           spec_path=spec_path, marker=marker, roots=roots, codec=codec,
                           controller=controller, attempt=AttemptBinding(authority, "run-1", "attempt-1"), write=write)


def test_v2_passive_agreement_activation_from_held_bytes(v2_operator):
    operator = v2_operator
    locator = binding.read_binding_locator(operator.path)
    passive = binding.load_v2_binding(operator.path, **operator.roots)
    assert isinstance(passive, binding.V2Binding)
    assert passive.binding_bytes == locator.binding_bytes and not operator.marker.exists()
    operator.codec.write_text('raise RuntimeError("path reread")')
    agreed = binding.reconcile_v2_binding(locator, passive, controller=operator.controller, attempt=operator.attempt)
    assert isinstance(agreed, binding.V2Binding) and not operator.marker.exists()
    activated = binding.activate_v2_binding(agreed)
    assert isinstance(activated, binding.V2Binding) and operator.marker.read_text() == "activated"
    assert activated.codec.PUBLIC_CODEC == "admitted_launch_envelope.v2"


@pytest.mark.parametrize("category", ["binding", "context", "spec", "codec", "validator"])
@pytest.mark.parametrize("root_kind", ["workspace", "target", "reference"])
def test_v2_full_load_exclusions(v2_operator, category, root_kind):
    operator = v2_operator
    directory = operator.roots["reference_roots"][0] if root_kind == "reference" else operator.roots[root_kind]
    document = dict(operator.document)
    if category == "binding":
        path = directory / "binding.json"
        path.write_bytes(operator.path.read_bytes())
    else:
        field = operator.document[category] if category in ("context", "spec") else operator.document["implementations"][category]["path"]
        selected = directory / Path(field).name
        selected.write_bytes(Path(field).read_bytes())
        selected.chmod(0o600)
        if category in ("context", "spec"):
            document[category] = str(selected)
        else:
            document["implementations"] = {**document["implementations"], category: {**document["implementations"][category], "path": str(selected)}}
        path = operator.write("changed-binding.json", document)
    assert binding.load_v2_binding(path, **operator.roots) == binding.Refused("untrusted_location")
    assert not operator.marker.exists()


@pytest.mark.parametrize("change", ["bytes", "root", "implementation"])
def test_v2_locator_disagreement_precedes_activation(v2_operator, change):
    operator = v2_operator
    locator = binding.read_binding_locator(operator.path)
    document = dict(operator.document)
    if change == "root":
        document["controller_root"] += "-replacement"
    elif change == "implementation":
        replacement = operator.path.parent / "replacement.py"
        replacement.write_text('raise RuntimeError("must remain passive")')
        document["implementations"] = {**document["implementations"], "codec": {"path": str(replacement), "sha256": binding.sha256(replacement.read_bytes())}}
    operator.path.write_text(json.dumps(document) + " ")
    passive = binding.load_v2_binding(operator.path, **operator.roots)
    assert isinstance(passive, binding.V2Binding)
    assert binding.reconcile_v2_binding(locator, passive, controller=operator.controller, attempt=operator.attempt) == binding.Refused("binding_invalid")
    assert binding.activate_v2_binding(passive) == binding.Refused("binding_invalid")
    assert not operator.marker.exists()


@pytest.mark.parametrize("change", ["assignment", "missing-context", "epoch", "slot", "roots", "missing-slot"])
def test_v2_controller_agreement_closed(v2_operator, change):
    import copy
    operator = v2_operator
    locator = binding.read_binding_locator(operator.path)
    passive = binding.load_v2_binding(operator.path, **operator.roots)
    document = copy.deepcopy(operator.controller)
    if change == "assignment": document["context"]["expected_assignment_digest"] = "e" * 64
    elif change == "missing-context": document["context"].pop("expected_crosswalk_ref")
    elif change == "epoch": document["context"]["policy_epoch"] = "epoch-2"
    elif change == "slot": document["slots"]["unexpected"] = "value"
    elif change == "roots": document["slots"]["workspace"] = str(operator.roots["target"])
    else: document["slots"].pop("reference_roots")
    assert binding.reconcile_v2_binding(locator, passive, controller=document, attempt=operator.attempt) == binding.Refused("binding_invalid")
    assert not operator.marker.exists()


def test_managed_binding_missing_passwd_has_no_fallback(monkeypatch):
    def missing(uid):
        raise KeyError(uid)
    monkeypatch.setattr(binding.pwd, "getpwuid", missing)
    assert binding._managed_binding() is None
    assert binding.read_binding_locator(None) == binding.Refused("binding_unavailable")
