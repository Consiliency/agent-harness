"""Tree commitment and held-capture boundary witnesses."""
from hashlib import sha256
from pathlib import Path
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


from test_supervised_launch import case as _case

case = _case
from test_supervised_launch_binding import v2_operator as _v2_operator

v2_operator = _v2_operator
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


def build_v2_attempt(operator, *, caller_context=None, secret=False):
    """Real local files and an offline provider; qualification is synthetic mechanics."""
    import copy
    import sys
    import time
    from types import SimpleNamespace
    import rfc8785
    from phase_loop_runtime.supervised_launch import prepare_launch_v2
    from phase_loop_runtime.supervised_envelope_v2 import _plain, _route_key
    launch = json.loads(operator.spec_path.read_bytes())["launch"]
    provider = Path(launch["executable_chain"][0]["path"]).with_name("codex")
    provider.write_text('import sys\ndata=sys.stdin.buffer.read()\nsys.stdout.buffer.write(b"")\n')
    provider.chmod(0o700)
    interpreter = Path(sys.executable).resolve()
    argv = [str(interpreter), str(provider)]
    template = dict(argv=argv, helpers=[dict(chain_index=0, argv_shift=1)], spawn_cwd=dict(namespace="workspace", path="."))
    Path(launch["template_path"]).write_text(json.dumps(template))
    launch["argv"] = argv
    launch["executable_chain"] = [dict(wire=dict(role="wrapper", locator_kind="declared", locator="python"), path=str(interpreter)),
                                   dict(wire=dict(role="executable", locator_kind="declared", locator="codex"), path=str(provider))]
    if secret:
        secret_path = operator.path.parent / "credential-source"
        secret_path.write_text("fixture-private-value-one")
        secret_path.chmod(0o600)
        launch["secret_sources"] = [dict(name="DEMO_SECRET", source="fixture-credentials", path=str(secret_path))]
        policy_path = Path(launch["environment_policy_path"])
        policy = json.loads(policy_path.read_bytes())
        policy["classification"]["DEMO_SECRET"] = {"secret": "fixture-credentials"}
        policy_path.write_text(json.dumps(policy))
    spec_document = json.loads(operator.spec_path.read_bytes())
    spec_document["launch"] = launch
    operator.spec_path.write_text(json.dumps(spec_document))
    initial = agreed_operator(operator)
    captured = capture_launch_v2(spec=initial.spec, context=initial.context, attempt=operator.attempt)
    assert isinstance(captured, CapturedLaunch), captured
    envelope = dict(schema="admitted_launch_envelope.v2", envelope_digest="0" * 64,
        assignment_digest=operator.attempt.assignment_digest,
        units=dict(target_unit_ids=["unit:target"], readonly_neighbor_unit_ids=[],
                   snapshot_ref=operator.context["expected_snapshot_ref"], crosswalk_ref=operator.context["expected_crosswalk_ref"]),
        workspace=dict(kind="separate_copy", repo_relative_locators=["src"]),
        enforcement=dict(tier="post_write_audit_only", required_constraints=[]), launch=_plain(captured.commitments),
        obligations=dict(definition_digests=[]), executable_dependencies=dict(declared=False, admitted_dependency_digest=None),
        caller_context={} if caller_context is None else caller_context, redaction_posture="digests_and_repo_relative_locators_only")
    record = dict(**_route_key(envelope), record_id="fixture-route", issuer_id="synthetic", policy_epoch="epoch-1",
        valid_from=time.time() - 60, expires_at=time.time() + 3600, grants={},
        credential_sources=list(captured.credential_sources), observed_versions=["fixture-1", "fixture-1"],
        evidence=[dict(path=launch["qualification_path"], sha256=sha256(Path(launch["qualification_path"]).read_bytes()).hexdigest())])
    captured.close()
    record_path = operator.write("route-record.json", record)
    context = json.loads(operator.context_path.read_bytes())
    record_digest = sha256(record_path.read_bytes()).hexdigest()
    context["qualified_routes"] = [dict(path=str(record_path), sha256=record_digest)]
    context["policy"]["issuer_records"] = {"synthetic": {"fixture-route": record_digest}}
    if caller_context:
        attestation = dict(record_id="fixture-context", issuer_id="synthetic", sha256=sha256(rfc8785.dumps(caller_context)).hexdigest(),
            assignment_digest=operator.attempt.assignment_digest, run_id=operator.attempt.run_id,
            attempt_id=operator.attempt.attempt_id, policy_epoch="epoch-1")
        context["caller_context_suitability"] = attestation
        context["policy"]["caller_context_records"] = {"synthetic": {"fixture-context": sha256(rfc8785.dumps(attestation)).hexdigest()}}
    operator.context_path.write_text(json.dumps(context))
    controller = copy.deepcopy(operator.controller)
    controller["context"] = {key: value for key, value in context.items() if key != "policy"}
    controller["context"]["qualified_routes"] = [record]
    envelope["envelope_digest"] = sha256(rfc8785.dumps({key: value for key, value in envelope.items() if key != "envelope_digest"})).hexdigest()
    raw = json.dumps(envelope, ensure_ascii=False).encode()
    controller["h"] = sha256(raw).hexdigest()
    operator.controller.clear()
    operator.controller.update(controller)
    agreed = agreed_operator(operator)
    active = binding.activate_v2_binding(agreed)
    assert isinstance(active, binding.V2Binding), active
    capture = capture_launch_v2(spec=active.spec, context=active.context, attempt=operator.attempt)
    assert isinstance(capture, CapturedLaunch), capture
    prepared = prepare_launch_v2(raw, binding=active, capture=capture, attempt=operator.attempt)
    from phase_loop_runtime.supervised_launch import PreparedLaunch
    assert isinstance(prepared, PreparedLaunch), prepared
    return SimpleNamespace(raw=raw, envelope=envelope, binding=active, capture=capture, prepared=prepared, operator=operator)


def test_v2_discard_closes_capture_and_spends_token(v2_operator):
    from phase_loop_runtime import supervised_launch as launch
    attempt = build_v2_attempt(v2_operator)
    launch.discard_admission(attempt.prepared)
    launch.discard_admission(attempt.prepared)
    assert attempt.capture._closed and attempt.prepared._token not in launch._TOKENS
    assert launch.consume_admission(attempt.prepared) == Refused("token_spent")


def test_v2_qualification_lifetime_is_rechecked(v2_operator, monkeypatch):
    import time
    from phase_loop_runtime import supervised_launch as launch
    attempt = build_v2_attempt(v2_operator)
    expires = min(record["expires_at"] for record in attempt.binding.context.qualified_routes)
    monkeypatch.setattr(time, "time", lambda: expires + 1)
    assert recheck_launch_v2(attempt.capture, context=attempt.binding.context) == launch.Refused("launch_input_unbound")
    assert attempt.capture._closed
    launch.discard_admission(attempt.prepared)


@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_v2_consumption_recheck_source_control(v2_operator, mutated):
    import inspect
    from phase_loop_runtime import supervised_launch as launch
    attempt = build_v2_attempt(v2_operator)
    reference = attempt.binding.spec.references[0][1].path
    reference.write_bytes(reference.read_bytes() + b"changed")
    function = launch.consume_admission
    if mutated:
        source = inspect.getsource(function)
        old = "refusal = recheck_launch_v2(capture, context=capture.context)"
        assert source.count(old) == 1
        namespace = dict(vars(launch))
        exec(compile(source.replace(old, "refusal = None"), "<v2-consume-control>", "exec"), namespace)
        function = namespace["consume_admission"]
    result = function(attempt.prepared)
    def assertion():
        assert isinstance(result, Refused) and result.reason == "launch_input_unbound"
    try:
        if mutated:
            with pytest.raises(AssertionError): assertion()
        else:
            assertion()
    finally:
        launch.discard_admission(attempt.prepared)


def test_v2_secret_rotation_keeps_both_commitments(v2_operator):
    from phase_loop_runtime.supervised_launch import discard_admission
    attempt = build_v2_attempt(v2_operator, secret=True)
    first = attempt.capture
    public = first.commitments
    local = first.local_digest
    discard_admission(attempt.prepared)
    path = first.spec.secret_sources[0][2]
    path.write_text("fixture-private-value-two")
    second = capture_launch_v2(spec=first.spec, context=attempt.binding.context, attempt=v2_operator.attempt)
    assert isinstance(second, CapturedLaunch), second
    assert second.local_digest == local and second.commitments == public
    assert "fixture-private-value" not in repr(second)
    second.close()
