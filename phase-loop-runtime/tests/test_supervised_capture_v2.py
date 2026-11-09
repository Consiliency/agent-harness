"""Tree commitment and held-capture boundary witnesses."""
from hashlib import sha256
import json

import pytest

from phase_loop_runtime.supervised_capture_v2 import _tree_manifest
from phase_loop_runtime.supervised_contracts import load_contract_bundle
from phase_loop_runtime.supervised_envelope_v2 import canonicalize_v2
from phase_loop_runtime.supervised_launch import _Refusal

CORPUS = json.loads(load_contract_bundle(version="v2").resource_bytes("conformance/envelope.v2.canonical.vectors.json"))


@pytest.mark.parametrize("case", CORPUS["tree_captures"], ids=lambda case: case["id"])
def test_published_tree_commitment(case):
    if case.get("unbindable"):
        with pytest.raises((_Refusal, ValueError, UnicodeError)):
            _tree_manifest(case["capture"])
    else:
        rows = _tree_manifest(case["capture"])
        assert rows == case["manifest"]
        assert sha256(canonicalize_v2(rows)).hexdigest() == case["sha256"]


@pytest.mark.parametrize("case", CORPUS["tree_alternates"], ids=lambda case: case["id"])
def test_tree_alternate_is_not_the_capture(case):
    source = next(row for row in CORPUS["tree_captures"] if row["id"] == case["of"])
    assert sha256(canonicalize_v2(_tree_manifest(source["capture"]))).hexdigest() != case["sha256"]


from test_supervised_launch import case
from test_supervised_launch_binding import v2_operator
from phase_loop_runtime import supervised_launch_binding as binding
from phase_loop_runtime.supervised_capture_v2 import CapturedLaunch, capture_launch_v2, recheck_launch_v2
from phase_loop_runtime.supervised_launch import Refused


def agreed_operator(operator):
    locator = binding.read_binding_locator(operator.path)
    passive = binding.load_v2_binding(operator.path, **operator.roots)
    assert isinstance(passive, binding.V2Binding)
    agreed = binding.reconcile_v2_binding(locator, passive, controller=operator.controller, attempt=operator.attempt)
    assert isinstance(agreed, binding.V2Binding)
    return agreed


def test_real_capture_and_complete_recheck(v2_operator):
    agreed = agreed_operator(v2_operator)
    capture = capture_launch_v2(spec=agreed.spec, context=agreed.context, attempt=v2_operator.attempt)
    assert isinstance(capture, CapturedLaunch), capture
    assert recheck_launch_v2(capture, context=agreed.context) is None
    with pytest.raises(AttributeError):
        capture.commitments = {}
    capture.close()
    capture.close()
    assert recheck_launch_v2(capture, context=agreed.context) == Refused("launch_input_unbound")


@pytest.mark.parametrize("material", ["instruction", "baseline", "template", "policy", "workspace", "context"])
def test_real_capture_mutations_refuse(v2_operator, material):
    operator = v2_operator
    agreed = agreed_operator(operator)
    capture = capture_launch_v2(spec=agreed.spec, context=agreed.context, attempt=operator.attempt)
    assert isinstance(capture, CapturedLaunch), capture
    paths = {"baseline": agreed.spec.references[0][1].path, "template": agreed.spec.template_path,
             "policy": agreed.spec.environment_policy_path, "context": operator.context_path}
    if material == "instruction":
        # The immutable inline bytes cannot be reassigned after capture.
        with pytest.raises(AttributeError):
            capture.instruction = b"changed"
        capture.close()
    elif material == "workspace":
        (agreed.spec.workspace / "new.txt").write_text("new material")
    else:
        paths[material].write_bytes(paths[material].read_bytes() + b" ")
    assert recheck_launch_v2(capture, context=agreed.context) == Refused("launch_input_unbound")
    assert capture._closed
