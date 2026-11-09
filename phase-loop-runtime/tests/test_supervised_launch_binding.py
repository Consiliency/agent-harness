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
