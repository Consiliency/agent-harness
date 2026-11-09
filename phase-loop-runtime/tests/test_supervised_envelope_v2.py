"""Public codec witnesses against the independently pinned canonical corpus."""
from hashlib import sha256
import json
import math
import struct

import pytest

from phase_loop_runtime.supervised_contracts import ContractError, load_contract_bundle
from phase_loop_runtime.supervised_envelope_v2 import canonicalize_v2, decode_v2, parse_v2

CORPUS = json.loads(load_contract_bundle(version="v2").resource_bytes("conformance/envelope.v2.canonical.vectors.json"))


@pytest.mark.parametrize("case", CORPUS["domain"], ids=lambda case: case["id"])
def test_published_number_domain(case):
    raw = case["token"].encode()
    if case["accept"]:
        assert canonicalize_v2(parse_v2(raw).value) == case["canonical"].encode()
    else:
        with pytest.raises(ContractError, match="record_json_invalid"):
            parse_v2(raw)


@pytest.mark.parametrize("case", CORPUS["documents"], ids=lambda case: case["id"])
def test_published_documents(case):
    raw = bytes.fromhex(case["raw_hex"]) if "raw_hex" in case else case["raw"].encode()
    if case.get("reject"):
        with pytest.raises(ContractError, match="record_json_invalid"):
            parse_v2(raw)
    else:
        result = canonicalize_v2(parse_v2(raw).value)
        assert result == case["canonical"].encode()
        assert sha256(result).hexdigest() == case["sha256"]


@pytest.mark.parametrize("case", CORPUS["numbers"], ids=lambda case: case["id"])
def test_published_binary64_primitives(case):
    value = struct.unpack(">d", bytes.fromhex(case["bits"]))[0]
    if not math.isfinite(value) or (value.is_integer() and abs(value) > 9007199254740991):
        with pytest.raises(ContractError):
            canonicalize_v2(value)
    else:
        assert canonicalize_v2(value).decode() == case["canonical"]


@pytest.mark.parametrize("value", [9007199254740992, float("inf"), float("nan"), "\ud800", {1: "key"}, object()])
def test_in_memory_domain(value):
    with pytest.raises(ContractError) as caught:
        canonicalize_v2(value)
    assert caught.value.code == "record_json_invalid" and caught.value.__context__ is None


def test_decoding_keeps_raw_and_public_identity_separate():
    cases = json.loads(load_contract_bundle(version="v2").resource_bytes("conformance/envelope.v2.vectors.json"))["cases"]
    envelope = cases[0]["input"]["envelope"]
    raw = json.dumps(envelope).encode()
    decoded = decode_v2(raw, bundle=load_contract_bundle(version="v2"))
    assert decoded.raw is raw
    assert decoded.public_digest == envelope["envelope_digest"]
    assert decoded.raw_digest == sha256(raw).hexdigest()
    with pytest.raises(TypeError):
        decoded.value["caller_context"]["changed"] = True


from types import SimpleNamespace
from phase_loop_runtime.supervised_capture_v2 import CapturedLaunch, _Delivery, _commit_material
from phase_loop_runtime.supervised_launch import AttemptBinding
from phase_loop_runtime.supervised_envelope_v2 import validate_v2_admission
from test_supervised_contracts_vectors import V2_CORPUS, expand_v2


def contract_capture(value, original):
    """Adapt fixture material to the production reducer; no semantic oracle lives here."""
    capture = CapturedLaunch()
    capture._closed, capture._spent = False, False
    policy = json.loads(value["launch_material"]["environment"]["policy"])
    environment = value["launch_material"]["process"]["worker"]["env"]
    secrets = [environment[name] for name, kind in policy["classification"].items()
               if isinstance(kind, dict) and "secret" in kind and name in environment]
    capture._delivery = _Delivery({}, secrets)
    stop = original["envelope"]["launch"]["stop"]
    capture.commitments, capture.diagnostics, capture.credential_sources, capture.uncheckable = _commit_material(
        value["launch_material"], timeout_seconds=stop["timeout_seconds"], deadline_action=stop["deadline_action"])
    attempt = AttemptBinding(value["validator_context"]["expected_assignment_digest"], "run-corpus", "attempt-corpus")
    context = SimpleNamespace(**value["validator_context"], policy_epoch="synthetic-corpus", revoked_record_ids=())
    payload = value["envelope"]["caller_context"]
    context.caller_context_suitability = dict(issuer_id="corpus", record_id="attestation", sha256=sha256(canonicalize_v2(payload)).hexdigest(),
        assignment_digest=attempt.assignment_digest, run_id=attempt.run_id, attempt_id=attempt.attempt_id,
        policy_epoch=context.policy_epoch)
    context.policy = {"caller_context_records": {"corpus": {"attestation": sha256(canonicalize_v2(context.caller_context_suitability)).hexdigest()}}}
    return capture, context, attempt


@pytest.mark.parametrize("case", [case for case in V2_CORPUS if case["kind"] == "admission"], ids=lambda case: case["id"])
def test_published_admission_production(case, request, monkeypatch):
    import os
    import subprocess
    effects = []
    def forbidden(*args, **kwargs):
        effects.append("spawn")
        raise AssertionError("unexpected admission effect")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for name in ("fork", "system", "posix_spawn", "posix_spawnp"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, forbidden)
    value = expand_v2(case)
    cases = {row["id"]: row for row in V2_CORPUS}
    original = case["input"] if case["role"] == "control" else cases[case["control"]]["input"]
    raw = json.dumps(value["envelope"], ensure_ascii=True, allow_nan=False).encode()
    try:
        envelope = decode_v2(raw, bundle=load_contract_bundle(version="v2"))
    except ContractError:
        observed = ("envelope_schema_invalid",)
    else:
        capture, context, attempt = contract_capture(value, original)
        decision = validate_v2_admission(envelope, context=context, capture=capture, attempt=attempt)
        observed = decision.diagnostics
    expected = case["expected"]
    stages = json.loads(load_contract_bundle(version="v2").resource_bytes("admitted-launch-envelope.v2.schema.json"))["x-evaluation-order"]["stages"]
    ordered = next((tuple(code for code in stage if code in expected) for stage in stages if set(expected) <= set(stage)), ())
    assert tuple(observed) == ordered, case["id"]
    assert not effects
    request.node.user_properties.extend([
        ("contract_case_id", case["id"]), ("contract_diagnostics", json.dumps(list(observed))),
        ("supported_route", "contract_only"), ("auxiliary_starts", "0"), ("chain_starts", "0")])


V2_GUARD_CODES = sorted({code for case in V2_CORPUS if case["kind"] == "admission"
                         for code in case["expected"]} - {"envelope_schema_invalid"})


@pytest.mark.parametrize("code", V2_GUARD_CODES)
@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_v2_reporting_guards_entered_in_source_copy(code, mutated):
    import ast
    import inspect
    from phase_loop_runtime import supervised_envelope_v2 as production
    case = next(row for row in V2_CORPUS if row["kind"] == "admission" and code in row["expected"])
    value = expand_v2(case)
    cases = {row["id"]: row for row in V2_CORPUS}
    original = case["input"] if case["role"] == "control" else cases[case["control"]]["input"]
    envelope = decode_v2(json.dumps(value["envelope"]).encode(), bundle=load_contract_bundle(version="v2"))
    capture, context, attempt = contract_capture(value, original)
    function = production._evaluate_v2_admission
    if mutated:
        class Bypass(ast.NodeTransformer):
            changed = 0
            def visit_Return(self, node):
                if any(isinstance(child, ast.Constant) and child.value == code for child in ast.walk(node)):
                    self.changed += 1
                    return ast.parse("return V2Decision(True, ())").body[0]
                return self.generic_visit(node)
            def visit_Expr(self, node):
                if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "append" and any(isinstance(child, ast.Constant) and child.value == code for child in ast.walk(node))):
                    self.changed += 1
                    return ast.Pass()
                return self.generic_visit(node)
            def visit_Assign(self, node):
                if any(isinstance(target, ast.Name) and target.id == "groups" for target in node.targets):
                    kept = [row for row in node.value.elts if row.elts[0].value != code]
                    self.changed += len(node.value.elts) - len(kept)
                    node.value.elts = kept
                return self.generic_visit(node)
        tree = ast.parse(inspect.getsource(function))
        bypass = Bypass()
        tree = ast.fix_missing_locations(bypass.visit(tree))
        assert bypass.changed == 1
        namespace = dict(vars(production))
        exec(compile(tree, "<v2-reporting-control>", "exec"), namespace)
        function = namespace["_evaluate_v2_admission"]
    decision = function(envelope, context=context, capture=capture, attempt=attempt)
    def production_assertion():
        assert code in decision.diagnostics
    if mutated:
        with pytest.raises(AssertionError): production_assertion()
    else:
        production_assertion()
