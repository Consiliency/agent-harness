"""Offline evidence controls; external producer authority remains unresolved."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "phase-loop-runtime/scripts/verify_supervised_v2_evidence.py"
spec = importlib.util.spec_from_file_location("supervised_v2_evidence", SCRIPT)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def command(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()


@pytest.fixture
def history(tmp_path):
    command(tmp_path, "init", "-q")
    command(tmp_path, "config", "user.name", "Offline fixture")
    command(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / "source.py").write_text("value = 1\n")
    def commit(message):
        command(tmp_path, "add", ".")
        command(tmp_path, "commit", "-qm", message)
        return command(tmp_path, "rev-parse", "HEAD")
    tested = commit("Input")
    receipt = tmp_path / evidence.RECEIPT
    receipt.parent.mkdir(parents=True)
    receipt.write_text("metadata\n")
    stamp = commit("Evidence")
    return tmp_path, tested, stamp, commit


def test_content_identity_and_receipt_only_stamp(history):
    repo, tested, stamp, commit = history
    evidence.check_stamp_delta(repo, tested, stamp)
    assert evidence.content_identity(repo, tested) == evidence.content_identity(repo, stamp)
    (repo / "source.py").write_text("value = 2\n")
    changed = commit("Changed input")
    with pytest.raises(evidence.EvidenceRefused, match="governing_content_changed"):
        evidence.check_stamp_delta(repo, tested, changed)


def test_uncommitted_governing_content_invalidates_assessment(history):
    repo, tested, stamp, _ = history
    record = dict(tested_head=tested, content_identity=evidence.content_identity(repo, tested))
    evidence.check_applicability(repo, record, stamp)
    (repo / "source.py").write_text("value = 2\n")
    with pytest.raises(evidence.EvidenceRefused, match="governing_content_changed"):
        evidence.check_applicability(repo, record, stamp)


class API:
    def __init__(self, responses):
        self.responses = responses
        self.observed = []
    def json(self, path):
        self.observed.append(path)
        return deepcopy(self.responses[path])
    def bytes(self, path):
        self.observed.append(path)
        return self.responses[path]


@pytest.mark.parametrize("mutation", [None, "head", "merge", "repository", "base"])
def test_squash_landing_requires_authenticated_correspondence(history, mutation):
    repo, tested, stamp, _ = history
    # An unrelated-history landing retains exactly the assessed non-evidence tree.
    tree = command(repo, "rev-parse", stamp + "^{tree}")
    landing = subprocess.check_output(["git", "-C", str(repo), "commit-tree", tree, "-m", "Landing"]).decode().strip()
    command(repo, "reset", "--hard", landing)
    record = dict(tested_head=tested, content_identity=evidence.content_identity(repo, tested), hosted_evidence={"pull_request": 1})
    pull = dict(merged=True, merge_commit_sha=landing, head={"sha": stamp, "repo": {"full_name": evidence.REPOSITORY}},
                base={"ref": "main", "repo": {"full_name": evidence.REPOSITORY}})
    if mutation == "head": pull["head"]["sha"] = "f" * 40
    if mutation == "merge": pull["merged"] = False
    if mutation == "repository": pull["base"]["repo"]["full_name"] = "fixture/other"
    if mutation == "base": pull["base"]["ref"] = "other"
    api = API({f"repos/{evidence.REPOSITORY}/pulls/1": pull})
    if mutation:
        with pytest.raises(evidence.EvidenceRefused):
            evidence.check_applicability(repo, record, landing, api=api)
    else:
        evidence.check_applicability(repo, record, landing, api=api)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'not-json'])
def test_metadata_json_is_strict(raw):
    with pytest.raises(evidence.EvidenceRefused, match="evidence_invalid"):
        evidence.strict_json(raw)


def test_negative_assessment_retains_observed_scope(history, monkeypatch):
    repo, _tested, stamp, _commit = history
    receipt = repo / "invalid-receipt.md"
    receipt.write_text('```json\n{"raw_payload":"inert-private-fixture"}\n```\n')
    output = repo / "assessment.json"
    monkeypatch.setattr(evidence.sys, "argv", ["evidence", "--repo", str(repo), "--receipt", str(receipt), "--output", str(output)])
    assert evidence.main() == 0
    result = json.loads(output.read_bytes())
    assert result["byte_pin_authority"] is False and result["refusal"] == "evidence_invalid"
    assert result["assessed_head"] == stamp and result["content_identity"] == evidence.content_identity(repo, stamp)
    assert "inert-private-fixture" not in output.read_text()


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped", None])
def test_producer_results_require_executed_passes(tmp_path, outcome):
    files = []
    for name in ("test_supervised_contracts", "test_supervised_envelope_v2", "test_supervised_worker", "test_supervised_v2_readiness"):
        path = tmp_path / (name + ".xml")
        child = "" if outcome is None else f"<{outcome}/>"
        path.write_text(f'<testsuite><testcase classname="{name}" name="test_control">{child}</testcase></testsuite>')
        files.append(path)
    if outcome:
        with pytest.raises(evidence.EvidenceRefused, match="producer_not_passed"):
            evidence.collect_producer_results(files, run_id="fixture", tested_head="a" * 40, resources={})
    else:
        rows = evidence.collect_producer_results(files, run_id="fixture", tested_head="a" * 40, resources={})
        assert all(len(group) == 1 for group in rows.values())


@pytest.mark.parametrize("control", ["observed", "different-reason", "different-node"])
def test_optional_dependency_unavailable_is_explicit(tmp_path, control):
    files = []
    for name in ("test_supervised_contracts", "test_supervised_envelope_v2", "test_supervised_worker", "test_supervised_v2_readiness"):
        path = tmp_path / (name + ".xml")
        path.write_text(f'<testsuite><testcase classname="{name}" name="test_control"/></testsuite>')
        files.append(path)
    name = "test_xdist_workers_remove_owned_audit_scratch" if control != "different-node" else "test_required_control"
    reason = "could not import 'xdist': No module named 'xdist'" if control != "different-reason" else "not executed"
    path = tmp_path / "retention.xml"
    path.write_text(f'<testsuite><testcase classname="test_output_retention" name="{name}"><skipped message="{reason}"/></testcase></testsuite>')
    files.append(path)
    if control != "observed":
        with pytest.raises(evidence.EvidenceRefused, match="producer_not_passed"):
            evidence.collect_producer_results(files, run_id="fixture", tested_head="a" * 40, resources={})
    else:
        rows = evidence.collect_producer_results(files, run_id="fixture", tested_head="a" * 40, resources={})
        unavailable = [row for group in rows.values() for row in group if row["outcome"] != "passed"]
        assert len(unavailable) == 1 and unavailable[0]["outcome"] == "unavailable"
        assert unavailable[0]["unavailable_reason"] == "xdist_unavailable"
        assert not unavailable[0]["production_witnesses"]


@pytest.mark.parametrize("field,value", [("head_sha", "b" * 40), ("path", "other.yml"), ("conclusion", "failure"), ("status", "in_progress")])
def test_run_identity_is_api_bound(field, value):
    run = dict(repository={"full_name": evidence.REPOSITORY}, path="workflow.yml", head_sha="a" * 40, status="completed", conclusion="success")
    run[field] = value
    with pytest.raises(evidence.EvidenceRefused, match="run_identity_invalid"):
        evidence.authenticate_run(API({f"repos/{evidence.REPOSITORY}/actions/runs/1": run}), 1, head="a" * 40, workflow="workflow.yml")


def test_latest_required_check_cannot_reuse_old_success():
    base = f"repos/{evidence.REPOSITORY}"
    check = dict(id=1, name="suite gate", head_sha="a" * 40, app={"slug": "github-actions"}, status="completed", conclusion="success",
                 details_url="https://github.com/Consiliency/agent-harness/actions/runs/3/job/4")
    latest = {**check, "id": 2, "status": "in_progress", "conclusion": None}
    api = API({base + "/branches/main/protection/required_status_checks": {"contexts": ["suite gate"]},
               base + "/rules/branches/main": [], base + "/commits/" + "a" * 40 + "/check-runs?per_page=100": {"total_count": 2, "check_runs": [check, latest]}})
    with pytest.raises(evidence.EvidenceRefused, match="required_check_missing"):
        evidence.authenticate_required_checks(api, "a" * 40)


@pytest.mark.parametrize("assessment_required", [False, True])
def test_same_run_required_checks_stay_closed(monkeypatch, assessment_required):
    base = f"repos/{evidence.REPOSITORY}"
    name = "supervised v2 evidence assessment" if assessment_required else "supervised v2 source verification"
    monkeypatch.setenv("GITHUB_RUN_ID", "3")
    check = dict(id=1, name=name, head_sha="a" * 40, app={"slug": "github-actions"},
        status="in_progress", conclusion=None, details_url="https://github.com/Consiliency/agent-harness/actions/runs/3/job/4")
    api = API({base + "/branches/main/protection/required_status_checks": {"contexts": [name]},
        base + "/rules/branches/main": [], base + "/commits/" + "a" * 40 + "/check-runs?per_page=100":
        {"total_count": 1, "check_runs": [check]}})
    expected = "assessment_check_self_dependency" if assessment_required else "required_check_missing"
    with pytest.raises(evidence.EvidenceRefused, match=expected):
        evidence.authenticate_required_checks(api, "a" * 40)


def test_external_producer_set_remains_explicit():
    assert {row[0] for row in evidence.MISSING_PRODUCERS} == {"controller", "display", "board", "president", "publication"}
    assert all(owner and edge for _, owner, edge in evidence.MISSING_PRODUCERS)


@pytest.mark.parametrize("change", [None, "noop", "head", "resource", "digest", "skipped"])
def test_publication_requires_full_api_bound_installed_proof(change):
    from phase_loop_runtime.supervised_contracts import V2_PUBLICATION_PINS
    head, run_id = "a" * 40, 3
    base = f"repos/{evidence.REPOSITORY}"
    publication = dict(contract=True, hosted_head=head, hosted_run_id=str(run_id),
        v2_resources={name: dict(sha256=pin[0], blob=pin[1]) for name, pin in V2_PUBLICATION_PINS.items()})
    if change == "noop": publication["contract"] = False
    if change == "head": publication["hosted_head"] = "b" * 40
    if change == "resource": publication["v2_resources"] = {}
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("schema-publication.json", json.dumps(publication))
        archive.writestr("schema-wheel.xml", '<testsuite><testcase classname="test_supervised_contracts" name="test_installed">'
                         + ('<skipped/>' if change == "skipped" else '') + '</testcase></testsuite>')
    raw = payload.getvalue()
    digest = sha256(raw).hexdigest() if change != "digest" else "f" * 64
    api = API({base + "/actions/runs/3": dict(repository={"full_name": evidence.REPOSITORY},
        path=".github/workflows/supervised-contract-intake.yml", head_sha=head, status="completed", conclusion="success"),
        base + "/actions/runs/3/artifacts?per_page=100": dict(total_count=1, artifacts=[dict(id=4,
            name="schema-publication-3", expired=False, size_in_bytes=len(raw), digest="sha256:" + digest)]),
        base + "/actions/artifacts/4/zip": raw})
    if change:
        with pytest.raises(evidence.EvidenceRefused): evidence.authenticate_publication(api, run_id, head)
    else:
        result = evidence.authenticate_publication(api, run_id, head)
        assert result["artifact_sha256"] == digest and result["contract"] is True


@pytest.fixture
def assessment(history, monkeypatch):
    from phase_loop_runtime.supervised_contracts import load_contract_bundle, V2_INPUT_ARTIFACT_SHA256
    repo, tested, stamp, _ = history
    bundle = load_contract_bundle(version="v2")
    resources = {name: sha256(raw).hexdigest() for name, raw in bundle._captured}
    hashes = {"source.py": sha256((repo / "source.py").read_bytes()).hexdigest()}
    monkeypatch.setattr(evidence, "SOURCE_PATHS", tuple(hashes))
    monkeypatch.setattr(evidence, "_schema_obligations", lambda _: ["named-obligation"])
    monkeypatch.setattr(evidence, "obligation_results", lambda *_: [{"id": "named-obligation", "outcome": "offline_production_covered"}])
    monkeypatch.setattr(evidence, "_current_producer_nodes", lambda *_: frozenset())
    groups = {name: [] for name in evidence.GROUPS}
    def row(node, case_id):
        return dict(test_node_id=node, case_or_control_id=case_id, resource_digests=resources,
                    production_witnesses=["phase_loop_runtime.supervised_envelope_v2.validate_v2_admission"], outcome="passed",
                    owner="CLOSEOUT", source_pointer=node.split("::", 1)[0], host="ai", runner_artifact_sha256="c" * 64, runner_artifact_ref="results.xml", runner_run_id="offline-fixture", runner_job_id="fixture-job", tested_head=tested)
    cases = evidence.strict_json(bundle.resource_bytes("conformance/envelope.v2.vectors.json"))["cases"]
    for case in cases:
        groups["intake_results"].append(row("tests/test_supervised_contracts.py::test_v2_published_schema_only[" + case["id"] + "]", case["id"]))
        if case["kind"] == "admission":
            item = row("tests/test_supervised_envelope_v2.py::test_admission[" + case["id"] + "]", case["id"])
            stages = evidence.strict_json(bundle.resource_bytes("admitted-launch-envelope.v2.schema.json"))["x-evaluation-order"]["stages"]
            ordered = next(([code for code in stage if code in case["expected"]] for stage in stages if set(case["expected"]) <= set(stage)), [])
            item.update(contract_diagnostics=ordered, supported_route="contract_only", auxiliary_starts="0", chain_starts="0")
            groups["admission_results"].append(item)
        else:
            groups["lifecycle_results"].append(row("tests/test_supervised_worker.py::test_v2_published_echo_at_real_writer_and_reader[" + case["id"] + "]", case["id"]))
    groups["readiness_results"].append(row("tests/test_supervised_v2_readiness.py::test_control", "control"))
    apply_cases = evidence.strict_json(bundle.resource_bytes("conformance/envelope.v2.apply.vectors.json"))["applications"]
    record = dict(schema="agent-harness.supervised-closeout.v2", byte_pin_authority=False, publisher_status="provisional",
        input_artifact_sha256=V2_INPUT_ARTIFACT_SHA256, tested_head=tested, content_identity=evidence.content_identity(repo, tested),
        source_hashes=hashes, runner_stamp=dict(source_tree_digest=sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
            host="ai", observed_commit=tested, run_id="offline-fixture", job_id="fixture-job", observed_utc="2026-11-09T00:00:00Z"), producer_results=groups, schema_obligations=["named-obligation"],
        obligation_results=evidence.obligation_results(repo, groups),
        external_evidence_intake=dict(controller_case_ids=sorted(case["id"] for case in apply_cases), status="upstream_phase_unmet"),
        spec_delta_closeout=dict(schema="spec_delta_closeout.v1", decision="canonical_spec_update", redaction_posture="metadata_only"), hosted_evidence={})
    return repo, record, stamp


def test_complete_offline_assessment_keeps_external_edges_blocked(assessment):
    repo, record, stamp = assessment
    result = evidence.evaluate(repo, record, current_head=stamp)
    assert result["offline_proof"] == "verified" and result["byte_pin_authority"] is False
    assert result["verification_status"] == "blocked" and result["human_required"] is False


@pytest.mark.parametrize("length", [8192, 8193])
def test_historical_deep_fixture_node_identity_bound(assessment, length):
    repo, record, stamp = assessment
    row = record["producer_results"]["readiness_results"][0]
    prefix = "tests/test_supervised_v2_readiness.py::test_control["
    row["test_node_id"] = prefix + "[" * (length - len(prefix) - 1) + "]"
    assert len(row["test_node_id"]) == length
    if length == 8192:
        assert evidence.evaluate(repo, record, current_head=stamp)["offline_proof"] == "verified"
    else:
        with pytest.raises(evidence.EvidenceRefused, match="producer_node_invalid"):
            evidence.evaluate(repo, record, current_head=stamp)


@pytest.mark.parametrize("control", ["\x00", "\t", "\x1f", "\x7f"])
def test_node_control_characters_refuse(assessment, control):
    repo, record, stamp = assessment
    record["producer_results"]["readiness_results"][0]["test_node_id"] += control
    with pytest.raises(evidence.EvidenceRefused, match="producer_node_invalid"):
        evidence.evaluate(repo, record, current_head=stamp)


def test_obligation_case_removal_enters_unpatched_reducer():
    record = evidence.read_receipt(ROOT / evidence.RECEIPT)
    producers = record["producer_results"]
    baseline = evidence.obligation_results(ROOT, producers)
    selected = next(row for row in baseline if row["outcome"] == "offline_production_covered")
    removed = set(selected["producer_nodes"])
    reduced = {group: [row for row in rows if row["test_node_id"] not in removed] for group, rows in producers.items()}
    changed = next(row for row in evidence.obligation_results(ROOT, reduced) if row["id"] == selected["id"])
    assert changed["outcome"] == "family_witnessed"
    assert changed != selected


@pytest.mark.parametrize("mutation", ["authority", "head", "resource", "skipped", "missing", "witness", "secret", "obligation", "external", "shared", "stamp-payload", "hosted-payload", "obligation-proof", "shared-stamp"])
def test_receipt_negative_controls_enter_production_verifier(assessment, mutation):
    repo, record, stamp = assessment
    row = record["producer_results"]["admission_results"][0]
    if mutation == "authority": record["byte_pin_authority"] = True
    elif mutation == "head": row["tested_head"] = "f" * 40
    elif mutation == "resource": row["resource_digests"] = {}
    elif mutation == "skipped": row["outcome"] = "skipped"
    elif mutation == "missing": record["producer_results"]["admission_results"].pop(0)
    elif mutation == "witness": row["production_witnesses"] = []
    elif mutation == "secret": row["raw_stream"] = "inert-fixture"
    elif mutation == "obligation": record["schema_obligations"] = []
    elif mutation == "external": record["external_evidence_intake"]["status"] = "passed"
    elif mutation == "stamp-payload": record["runner_stamp"]["payload"] = "inert-fixture"
    elif mutation == "hosted-payload": record["hosted_evidence"]["payload"] = "inert-fixture"
    elif mutation == "obligation-proof": record["obligation_results"] = []
    elif mutation == "shared-stamp": record["source_hashes"]["phase-loop-runtime/tests/test_stamp_evidence_receipt.py"] = "f" * 64
    else: record["source_hashes"]["CHANGELOG.md"] = "f" * 64
    with pytest.raises(evidence.EvidenceRefused):
        evidence.evaluate(repo, record, current_head=stamp)


INAPPLICABLE = {"assessment_inapplicable", "source_binding_stale", "producer_nodes_missing",
                "landing_correspondence_unavailable", "governing_content_changed", "git_identity_unavailable"}


def assert_receipt_applicability(repo, record, head=None):
    head = head or evidence.git(repo, "rev-parse", "HEAD").decode().strip()
    if evidence.content_identity(repo, head) == record["content_identity"]:
        try:
            result = evidence.evaluate(repo, record, current_head=head)
        except evidence.EvidenceRefused as refused:
            assert str(refused) in {"landing_correspondence_unavailable", "git_identity_unavailable"}
            assert record["byte_pin_authority"] is False
            return
        assert result["byte_pin_authority"] is False and result["verification_status"] == "blocked"
        assert result["blocker_class"] == "upstream_phase_unmet" and result["offline_proof"] == "verified"
    else:
        with pytest.raises(evidence.EvidenceRefused) as refused:
            evidence.evaluate(repo, record, current_head=head)
        assert str(refused.value) in INAPPLICABLE
        assert record["byte_pin_authority"] is False


def test_post_stamp_governing_change_is_inapplicable(assessment):
    repo, record, stamp = assessment
    assert_receipt_applicability(repo, record, stamp)
    (repo / "source.py").write_text("value = 2\n")
    command(repo, "add", ".")
    command(repo, "commit", "-qm", "Later governing input")
    assert_receipt_applicability(repo, record)



def test_offline_squash_correspondence_remains_unverified(assessment):
    repo, record, stamp = assessment
    tree = command(repo, "rev-parse", stamp + "^{tree}")
    landing = subprocess.check_output(["git", "-C", str(repo), "commit-tree", tree, "-m", "Squash landing"]).decode().strip()
    command(repo, "reset", "--hard", landing)
    assert evidence.content_identity(repo, landing) == record["content_identity"]
    assert_receipt_applicability(repo, record, landing)


def test_receipt_current():
    record = evidence.read_receipt(ROOT / evidence.RECEIPT)
    assert max(len(row["test_node_id"]) for rows in record["producer_results"].values() for row in rows) == 4063
    assert_receipt_applicability(ROOT, record)
