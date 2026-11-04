"""Remove real production guards in isolated module copies; witnesses must go red."""
import ast
from pathlib import Path
import sys
from types import ModuleType

import pytest

from phase_loop_runtime import supervised_launch as launch
from test_supervised_launch import (
    case as _case, consumption_witness, identity_witness, prepare, qualify, reference_witness, refused, storage_witness,
    executable_owner_witness, capture_witness,
    finite_witness, codec_witness, root_storage_witness, location_witness, nesting_witness, git_data_witness,
)

case = _case


def mutant(monkeypatch, production, control):
    source = Path(production.__file__).read_text()
    if control == "reference_nofollow":
        source = source.replace("nofollow=True, regular=True, bounded=False", "nofollow=False, regular=True, bounded=False")
    elif control == "token":
        source = source.replace("_TOKENS.pop(prepared._token, None)", "_TOKENS.get(prepared._token, None)")
    elif control == "identity_digest":
        source = source.replace('payload.pop("baseline")', 'payload.pop("baseline")\n    payload.pop("executable")\n    payload.pop("wrappers")')
    elif control == "workspace":
        source = source.replace('if tier == "provider_readonly_patch_return_audit":', 'if False:', 1)
    elif control == "trusted_import":
        source = source.replace("module = _load_absolute(path, data)", "module = __import__(path.stem)")
    elif control == "route_classification":
        source = source.replace('if classification != "provider_free":', 'if False:')
    elif control == "workspace_uninspectable":
        source = source.replace('raise _Refusal("workspace_uninspectable") from error', 'return')
    elif control == "executable_owner_policy":
        source = source.replace('operator_owned=False', 'operator_owned=True')
    elif control == "capture_once":
        source = source.replace('capture = EnvelopeCapture(', '_json(envelope_bytes)\n        sha256(envelope_bytes)\n        capture = EnvelopeCapture(')
    elif control == "workspace_ancestry":
        source = source.replace('return any(_inode(parent.stat()) == identity for parent in (path, *path.parents))',
                                'return path == root or root in path.parents')
    elif control == "direct_route":
        source = source.replace('refuse_unwired_dependency_route("supervised-launch")', 'pass')
    else:
        reason = {"consume_class": "workspace_changed", "consume_device": "device_changed",
                  "consume_inode": "inode_changed", "consume_executable": "executable_changed",
                  "consume_wrapper": "wrapper_changed", "qualification": "qualification_invalid",
                  "typed_admit": "admit_required"}.get(control, control)
        tree = ast.parse(source)
        matches = [node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                   and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                   and node.value.func.id == "_require" and len(node.value.args) == 2
                   and isinstance(node.value.args[1], ast.Constant) and node.value.args[1].value == reason]
        assert len(matches) == (2 if control in {"untrusted_location", "canonical_path_required"} else 1), (control, matches)
        lines = source.splitlines(keepends=True)
        for node in sorted(matches, key=lambda node: node.lineno, reverse=True):
            lines[node.lineno - 1:node.end_lineno] = [" " * node.col_offset + "pass\n"]
        source = "".join(lines)
    assert source != Path(production.__file__).read_text(), control
    name = "phase_loop_runtime._mutation_" + control
    module = ModuleType(name)
    module.__file__ = production.__file__
    module.__package__ = "phase_loop_runtime"
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source, production.__file__, "exec"), module.__dict__)
    return module


CONTROLS = ["admit_binding", "typed_admit", "identity_digest", "token", "qualification", "workspace",
            "tier_unsupported", "constraints_unsupported", "reference_digest",
            "workspace_shared", "workspace_uninspectable",
            "executable_owner_policy",
            "capture_once",
            "consume_class", "consume_device", "consume_inode", "consume_executable", "consume_wrapper",
            "reference_root", "reference_nofollow", "reference_regular", "reference_cap", "aggregate_cap", "envelope_cap"]
CONTROLS += ["nonfinite", "workspace_root_shared", "untrusted_location", "workspace_ancestry",
             "canonical_path_required", "codec_changed_envelope", "workspace_gitfile"]


def witness(case, module, monkeypatch, control):
    if control == "nonfinite":
        finite_witness(case, module)
    elif control == "workspace_root_shared":
        root_storage_witness(case, module, monkeypatch)
    elif control == "untrusted_location":
        location_witness(case, module, monkeypatch)
    elif control == "workspace_ancestry":
        nesting_witness(case, module, monkeypatch)
    elif control == "canonical_path_required":
        case.envelope["launch_inputs"]["workspace"] = "/" + case.envelope["launch_inputs"]["workspace"]
        refused(case, module, reason="canonical_path_required")
    elif control == "codec_changed_envelope":
        codec_witness(case, module)
    elif control == "workspace_gitfile":
        git_data_witness(case, module)
    elif control.startswith("consume_"):
        consumption_witness(case, module, monkeypatch, control)
    elif control in {"workspace_shared", "workspace_uninspectable"}:
        storage_witness(case, module, monkeypatch, control)
    elif control == "executable_owner_policy":
        executable_owner_witness(case, module, monkeypatch)
    elif control == "capture_once":
        capture_witness(case, module, monkeypatch)
    elif control == "reference_digest":
        case.envelope["launch_inputs"]["instruction"]["digest"] = "stale"
        refused(case, module)
    elif control.startswith("reference_") or control in {"aggregate_cap", "envelope_cap"}:
        reference_witness(case, module, control)
    elif control == "identity_digest":
        identity_witness(case, module)
    elif control == "admit_binding":
        refused(case, module, validator=lambda view: module.Admit("stale", "stale"))
    elif control == "typed_admit":
        class Impostor:
            pass
        def fake(view):
            value = Impostor()
            value.launch_digest = view.launch_digest
            value.attempt_id = view.envelope["attempt_id"]
            return value
        refused(case, module, validator=fake)
    elif control == "token":
        prepared = prepare(case, module)
        assert isinstance(module.consume_admission(prepared), module.LaunchInputs)
        assert module.consume_admission(prepared) == module.Refused("token_spent")
    elif control == "qualification":
        path = qualify(case)
        path.write_text(path.read_text().replace('"write_attempt_refused": true', '"write_attempt_refused": false'))
        refused(case, module)
    elif control == "workspace":
        qualify(case)
        (case.root / "workspace/.git").write_text("gitdir: ../target/.git")
        refused(case, module)
    elif control == "tier_unsupported":
        case.envelope["launch_inputs"]["tier"] = "os_enforced"
        refused(case, module)
    elif control == "constraints_unsupported":
        case.envelope["launch_inputs"]["constraints"] = ["network_denial"]
        refused(case, module)


@pytest.mark.parametrize("control", CONTROLS)
def test_production_control_witness(case, monkeypatch, control):
    witness(case, launch, monkeypatch, control)


@pytest.mark.parametrize("control", CONTROLS)
def test_supervised_launch_mutations(case, monkeypatch, control):
    # The same assertion is separately exercised against the intact production module.
    module = mutant(monkeypatch, launch, control)
    with pytest.raises(AssertionError):
        witness(case, module, monkeypatch, control)
