"""Metadata-only CLOSEOUT evidence reduction; provisional intake never grants authority."""
from __future__ import annotations

import argparse
from functools import lru_cache
import sys
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import rfc8785

REPOSITORY = "Consiliency/agent-harness"
RECEIPT = "plans/evidence/supervised-worker/CLOSEOUT.md"
GROUPS = ("intake_results", "admission_results", "lifecycle_results", "readiness_results")
SHARED = frozenset({"CHANGELOG.md", "plans/manifest.json", "phase-loop-runtime/pyproject.toml", "phase-loop-runtime/uv.lock",
                   "phase-loop-runtime/tests/data/seat_launch_references.json", "phase-loop-runtime/tests/test_gate_a_wheel_isolation.py",
                   "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py",
                   "phase-loop-runtime/tests/test_seat_reference_inventory.py"})
SOURCE_PATHS = (
    "phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_envelope_v2.py",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_capture_v2.py",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_echo.py",
    "phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py",
    "phase-loop-runtime/scripts/verify_supervised_v2.sh",
    "phase-loop-runtime/scripts/verify_supervised_v2_evidence.py",
    "phase-loop-runtime/scripts/verify_supervised_contract_publication.py",
    "phase-loop-runtime/tests/test_supervised_envelope_v2.py",
    "phase-loop-runtime/tests/test_supervised_capture_v2.py",
    "phase-loop-runtime/tests/test_supervised_v2_readiness.py",
    "phase-loop-runtime/tests/historical_receipts.py",
    "phase-loop-runtime/tests/test_supervised_contracts.py",
    "phase-loop-runtime/tests/test_supervised_contracts_vectors.py",
    "phase-loop-runtime/tests/test_supervised_contracts_mutations.py",
    "phase-loop-runtime/tests/test_supervised_contracts_receipt.py",
    "phase-loop-runtime/tests/test_supervised_launch.py",
    "phase-loop-runtime/tests/test_supervised_launch_binding.py",
    "phase-loop-runtime/tests/test_supervised_launch_route.py",
    "phase-loop-runtime/tests/test_supervised_launch_mutations.py",
    "phase-loop-runtime/tests/test_supervised_launch_receipt.py",
    "phase-loop-runtime/tests/test_supervised_worker.py",
    "phase-loop-runtime/tests/test_supervised_worker_cli.py",
    "phase-loop-runtime/tests/test_supervised_worker_receipt.py",
    "phase-loop-runtime/tests/test_run_status_receipt.py",
    "plans/artifacts/v12-CLOSEOUT-inputs.md",
    "plans/artifacts/v12-CLOSEOUT-landed-binding.md",
    "plans/artifacts/v12-CLOSEOUT-binding-location.md",
    "plans/artifacts/v12-v13-replan-ownership.md",
)
CHECK_WORKFLOWS = {
    "supervised contract publication": ".github/workflows/supervised-contract-intake.yml",
    "supervised v2 evidence assessment": ".github/workflows/supervised-v2-evidence.yml",
    "suite gate": ".github/workflows/test.yml", "lint (pyflakes)": ".github/workflows/test.yml",
    "chronology retention guard": ".github/workflows/test.yml", "docs-freshness audit": ".github/workflows/docs-audit.yml",
    "gitleaks": ".github/workflows/scrub.yml", "check": ".github/workflows/release-consistency.yml",
}
MISSING_PRODUCERS = (
    ("controller", "controller application maintainer", "13 authenticated apply outcomes"),
    ("display", "display consumer maintainer", "byte-exact reader reconciliation"),
    ("board", "review evidence publisher", "authenticated board publisher binding"),
    ("president", "review evidence publisher", "authenticated separate-president publisher binding"),
    ("publication", "contract publisher", "reviewed non-provisional successor input"),
)


class EvidenceRefused(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise EvidenceRefused(code)


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "evidence_invalid")
            result[key] = value
        return result
    def invalid(_):
        raise EvidenceRefused("evidence_invalid")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise EvidenceRefused("evidence_invalid") from None


def git(repo, *args):
    try:
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise EvidenceRefused("git_identity_unavailable") from None


def content_identity(repo: Path, ref: str) -> str:
    rows = []
    for raw in git(repo, "ls-tree", "-rz", ref).split(b"\0"):
        if not raw:
            continue
        metadata, path = raw.split(b"\t", 1)
        mode, _kind, blob = metadata.decode("ascii").split()
        path = path.decode("utf-8")
        if path != RECEIPT:
            rows.append([path, mode, blob])
    return sha256(rfc8785.dumps(sorted(rows))).hexdigest()


def check_stamp_delta(repo, tested_head, stamp_head):
    require(re.fullmatch(r"[0-9a-f]{40}", tested_head or "") is not None, "tested_head_invalid")
    require(re.fullmatch(r"[0-9a-f]{40}", stamp_head or "") is not None, "stamp_head_invalid")
    git(repo, "merge-base", "--is-ancestor", tested_head, stamp_head)
    paths = set(git(repo, "diff", "--name-only", "--no-renames", tested_head, stamp_head).decode().splitlines())
    require(paths <= {RECEIPT}, "governing_content_changed")
    require(content_identity(repo, tested_head) == content_identity(repo, stamp_head), "governing_content_changed")


def check_applicability(repo, record, current_head, *, api=None):
    require(content_identity(repo, current_head) == record["content_identity"], "assessment_inapplicable")
    try:
        check_stamp_delta(repo, record["tested_head"], current_head)
    except EvidenceRefused:
        require(api is not None, "landing_correspondence_unavailable")
        number = record["hosted_evidence"].get("pull_request")
        require(type(number) is int and number > 0, "landing_correspondence_unavailable")
        pull = api.json(f"repos/{REPOSITORY}/pulls/{number}")
        require(pull["merged"] is True and pull["base"]["repo"]["full_name"] == REPOSITORY
                and pull["base"]["ref"] == "main" and pull["head"]["repo"]["full_name"] == REPOSITORY,
                "landing_correspondence_invalid")
        check_stamp_delta(repo, record["tested_head"], pull["head"]["sha"])
        git(repo, "merge-base", "--is-ancestor", pull["merge_commit_sha"], current_head)
        require(content_identity(repo, pull["merge_commit_sha"]) == record["content_identity"], "assessment_inapplicable")
    dirty = set(git(repo, "diff", "--name-only", current_head).decode().splitlines())
    require(dirty <= {RECEIPT}, "governing_content_changed")


def read_receipt(path):
    blocks = re.findall(rb"```json\n(.*?)\n```", path.read_bytes(), re.S)
    require(len(blocks) == 1, "receipt_invalid")
    return strict_json(blocks[0])


def _group(filename):
    if filename in {"test_supervised_contracts", "test_supervised_contracts_vectors", "test_supervised_contracts_mutations",
                    "test_supervised_contracts_receipt", "test_gate_a_wheel_isolation", "test_ci_chronology_scope", "test_ci_offload_lock"}:
        return "intake_results"
    if filename == "test_supervised_v2_readiness":
        return "readiness_results"
    if filename.startswith("test_supervised_launch") or filename in {"test_supervised_capture_v2", "test_supervised_envelope_v2"}:
        return "admission_results"
    return "lifecycle_results"


def collect_producer_results(paths, *, run_id, tested_head, resources, job_id="offline-fixture"):
    groups = {group: [] for group in GROUPS}
    seen = set()
    for path in paths:
        raw = path.read_bytes()
        artifact_digest = sha256(raw).hexdigest()
        for case in ET.fromstring(raw).iter("testcase"):
            require(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")), "producer_not_passed")
            components = case.attrib["classname"].split(".")
            filename = next((part for part in components if part.startswith("test_")), None)
            require(filename is not None, "producer_node_invalid")
            classes = components[components.index(filename) + 1:]
            node = "tests/" + filename + ".py::" + "::".join([*classes, case.attrib["name"]])
            require(node not in seen, "producer_duplicate")
            seen.add(node)
            properties = {item.attrib["name"]: item.attrib["value"] for item in case.findall("properties/property")}
            witnesses = strict_json(properties.get("production_witnesses", "[]"))
            require(isinstance(witnesses, list) and all(type(item) is str for item in witnesses), "witness_invalid")
            row = dict(test_node_id=node, case_or_control_id=properties.get("contract_case_id", case.attrib["name"]),
                       resource_digests=resources, production_witnesses=witnesses, outcome="passed",
                       runner_artifact_sha256=artifact_digest, runner_artifact_ref=path.name,
                       runner_run_id=run_id, runner_job_id=job_id, tested_head=tested_head, owner="CLOSEOUT",
                       source_pointer=node.split("::", 1)[0], host="ai")
            if "contract_diagnostics" in properties:
                row["contract_diagnostics"] = strict_json(properties["contract_diagnostics"])
                row["supported_route"] = properties["supported_route"]
                row["auxiliary_starts"] = properties["auxiliary_starts"]
                row["chain_starts"] = properties["chain_starts"]
            groups[_group(filename)].append(row)
    require(all(groups.values()), "producer_group_missing")
    return groups


@lru_cache(maxsize=8)
def _current_producer_nodes(repo, tested_head):
    repo = Path(repo)
    binding = (repo / "plans/artifacts/v12-CLOSEOUT-landed-binding.md").read_text()
    selectors = list(dict.fromkeys(selector for group in re.findall(r"^- V[0-3]: (.+)$", binding, re.M)
                                  for selector in re.findall(r"`([^`]+)`", group)))
    require(bool(selectors), "producer_inventory_invalid")
    nodes = set()
    for selector in selectors:
        try:
            result = subprocess.run(["timeout", "900", sys.executable, "-m", "pytest", "--collect-only", "-q",
                "-p", "no:cacheprovider", selector], cwd=repo / "phase-loop-runtime", capture_output=True, text=True, timeout=910)
        except (OSError, subprocess.SubprocessError):
            raise EvidenceRefused("producer_inventory_unavailable") from None
        require(result.returncode == 0, "producer_inventory_unavailable")
        selected = {line.strip() for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line}
        require(bool(selected), "producer_inventory_unavailable")
        nodes.update(selected)
    return frozenset(node for node in nodes if not node.endswith("::test_receipt_current"))


def _schema_obligations(repo):
    schema = read_receipt(repo / "plans/evidence/supervised-worker/SCHEMA.md")
    return sorted({row["id"] for group in ("coverage_inventory", "semantic_inventory", "semantic_cases") for row in schema[group]})


def obligation_results(repo, producers):
    """Link the historical inventory to executed production families and cases."""
    schema = read_receipt(repo / "plans/evidence/supervised-worker/SCHEMA.md")
    rows = [row for group in producers.values() for row in group if row["production_witnesses"]]
    result = []
    for group in ("coverage_inventory", "semantic_inventory", "semantic_cases"):
        for obligation in schema[group]:
            identifier = obligation["id"]
            vectors = set(obligation.get("vector_ids", ()))
            if group == "semantic_cases": vectors.add(identifier)
            matched = [row for row in rows if any(row["test_node_id"].endswith("[" + case + "]") for case in vectors)
                       and ("contract_diagnostics" in row or row["test_node_id"].startswith("tests/test_run_status"))]
            if not matched:
                if identifier.startswith(("status:", "journal:", "named:status", "named:lifecycle", "named:identity-journal")):
                    prefixes = ("tests/test_run_status.py::", "tests/test_run_status_projection.py::")
                elif identifier in {"named:evidence-producer-binding", "named:proposal-attempt-independence", "named:identity-public-replay", "named:identity-units"}:
                    prefixes = ("tests/test_supervised_worker.py::",)
                else:
                    prefixes = ("tests/test_supervised_capture_v2.py::", "tests/test_supervised_envelope_v2.py::")
                matched = [row for row in rows if row["test_node_id"].startswith(prefixes)]
            require(matched, "obligation_proof_missing")
            result.append(dict(id=identifier, source_pointer=obligation.get("source_pointer", obligation.get("family")),
                owner="CLOSEOUT", outcome="offline_production_covered", producer_nodes=sorted(row["test_node_id"] for row in matched)))
    return sorted(result, key=lambda row: row["id"])


def verify_offline(repo, record):
    from phase_loop_runtime.supervised_contracts import V2_INPUT_ARTIFACT_SHA256, load_contract_bundle
    bundle = load_contract_bundle(version="v2")
    require(record["schema"] == "agent-harness.supervised-closeout.v2" and record["byte_pin_authority"] is False
            and record["publisher_status"] == "provisional", "authority_invalid")
    require(record["input_artifact_sha256"] == V2_INPUT_ARTIFACT_SHA256, "input_seal_invalid")
    required_keys = {"schema", "byte_pin_authority", "publisher_status", "input_artifact_sha256", "tested_head",
                     "content_identity", "source_hashes", "runner_stamp", "producer_results", "schema_obligations",
                     "obligation_results", "external_evidence_intake", "spec_delta_closeout", "hosted_evidence"}
    require(set(record) == required_keys, "receipt_invalid")
    stamp = record["runner_stamp"]
    require(set(stamp) == {"host", "observed_commit", "run_id", "job_id", "observed_utc", "source_tree_digest"}, "runner_stamp_invalid")
    require(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", stamp["run_id"]) is not None
            and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", stamp["job_id"]) is not None
            and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z", stamp["observed_utc"]) is not None, "runner_identity_invalid")
    require(set(record["hosted_evidence"]) <= {"publication_run_id", "gate_a_run_id", "verifier_run_id", "pull_request"}
            and all(value is None or type(value) is int and value > 0 for value in record["hosted_evidence"].values()), "hosted_identity_invalid")
    hashes = record["source_hashes"]
    require(set(hashes) == set(SOURCE_PATHS), "source_inventory_invalid")
    for path, digest in hashes.items():
        require(path not in SHARED and not path.startswith(("docs/", ".github/workflows/")), "shared_source_pin")
        require(sha256((repo / path).read_bytes()).hexdigest() == digest, "source_binding_stale")
        require(sha256(git(repo, "show", record["tested_head"] + ":" + path)).hexdigest() == digest, "tested_source_stale")
    require(record["runner_stamp"]["source_tree_digest"] == sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), "runner_stamp_invalid")
    require(record["runner_stamp"]["host"] == "ai" and record["runner_stamp"]["observed_commit"] == record["tested_head"], "runner_identity_invalid")
    require(content_identity(repo, record["tested_head"]) == record["content_identity"], "content_identity_invalid")
    resources = {name: sha256(data).hexdigest() for name, data in bundle._captured}
    groups = record["producer_results"]
    require(set(groups) == set(GROUPS) and all(groups.values()), "producer_group_missing")
    nodes = set()
    for group, rows in groups.items():
        for row in rows:
            expected_fields = {"test_node_id", "case_or_control_id", "resource_digests", "production_witnesses", "outcome",
                               "runner_artifact_sha256", "runner_artifact_ref", "runner_run_id", "runner_job_id", "tested_head", "owner", "source_pointer", "host"}
            require(expected_fields <= set(row) <= expected_fields | {"contract_diagnostics", "supported_route", "auxiliary_starts", "chain_starts"}, "producer_row_invalid")
            node = row["test_node_id"]
            require(row["owner"] == "CLOSEOUT" and row["host"] == "ai" and row["source_pointer"] == node.split("::", 1)[0], "producer_identity_invalid")
            require(type(node) is str and len(node) <= 2048 and re.fullmatch(r"tests/test_[A-Za-z0-9_]+\.py::[^\r\n]+", node) is not None,
                    "producer_node_invalid")
            require(all(re.fullmatch(r"[A-Za-z0-9_.<>]+", symbol) is not None for symbol in row["production_witnesses"]), "witness_invalid")
            require(re.fullmatch(r"[A-Za-z0-9_.-]+\.xml", row["runner_artifact_ref"]) is not None, "producer_artifact_invalid")
            require(node not in nodes and row["outcome"] == "passed", "producer_not_passed")
            nodes.add(node)
            require(row["resource_digests"] == resources and row["tested_head"] == record["tested_head"], "producer_identity_invalid")
            require(re.fullmatch(r"[0-9a-f]{64}", row["runner_artifact_sha256"]) is not None
                    and row["runner_run_id"] == record["runner_stamp"]["run_id"]
                    and row["runner_job_id"] == record["runner_stamp"]["job_id"], "producer_artifact_invalid")
    cases = strict_json(bundle.resource_bytes("conformance/envelope.v2.vectors.json"))["cases"]
    stages = strict_json(bundle.resource_bytes("admitted-launch-envelope.v2.schema.json"))["x-evaluation-order"]["stages"]
    rows = {row.get("case_or_control_id"): row for row in groups["admission_results"] if "contract_diagnostics" in row}
    for case in cases:
        if case["kind"] == "admission":
            require(case["id"] in rows, "admission_case_missing")
            row = rows[case["id"]]
            ordered = next(([code for code in stage if code in case["expected"]] for stage in stages if set(case["expected"]) <= set(stage)), [])
            require(row["contract_diagnostics"] == ordered and row["production_witnesses"], "admission_proof_invalid")
            require(row["auxiliary_starts"] == "0" and row["chain_starts"] == "0", "admission_effect_invalid")
            require(row["supported_route"] == "contract_only", "route_claim_invalid")
        else:
            require(any(node.endswith("::test_v2_published_echo_at_real_writer_and_reader[" + case["id"] + "]") for node in nodes), "echo_case_missing")
        require(any(node.endswith("::test_v2_published_schema_only[" + case["id"] + "]") for node in nodes), "schema_case_missing")
    require(_current_producer_nodes(str(repo), record["tested_head"]) <= nodes, "producer_nodes_missing")
    require(record["schema_obligations"] == _schema_obligations(repo), "obligation_inventory_invalid")
    require(record["obligation_results"] == obligation_results(repo, groups), "obligation_proof_invalid")
    apply_cases = strict_json(bundle.resource_bytes("conformance/envelope.v2.apply.vectors.json"))["applications"]
    external = record["external_evidence_intake"]
    require(set(external) == {"controller_case_ids", "status"} and external["controller_case_ids"] == sorted(case["id"] for case in apply_cases)
            and len(external["controller_case_ids"]) == 13 and external["status"] == "upstream_phase_unmet", "external_intake_invalid")
    require(record["spec_delta_closeout"] == dict(schema="spec_delta_closeout.v1", decision="canonical_spec_update", redaction_posture="metadata_only"), "spec_closeout_invalid")
    return dict(verification_status="blocked", blocker_class="upstream_phase_unmet", human_required=False,
                byte_pin_authority=False, offline_proof="verified", missing_producers=[dict(id=key, owner=owner, blocked_edge=edge)
                for key, owner, edge in MISSING_PRODUCERS])


class GitHubEvidence:
    def json(self, path):
        try:
            raw = subprocess.check_output(["gh", "api", path], stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            raise EvidenceRefused("authenticated_evidence_unavailable") from None
        return strict_json(raw)

    def bytes(self, path):
        try:
            raw = subprocess.check_output(["gh", "api", path], stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            raise EvidenceRefused("authenticated_evidence_unavailable") from None
        require(len(raw) <= 16777216, "artifact_size_invalid")
        return raw


def authenticate_run(api, run_id, *, head, workflow):
    require(type(run_id) is int and run_id > 0, "run_identity_invalid")
    run = api.json(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    require(run["repository"]["full_name"].lower() == REPOSITORY.lower() and run["path"] == workflow
            and run["head_sha"] == head and run["status"] == "completed" and run["conclusion"] == "success", "run_identity_invalid")
    return run


def authenticate_required_checks(api, head):
    protection = api.json(f"repos/{REPOSITORY}/branches/main/protection/required_status_checks")
    rules = api.json(f"repos/{REPOSITORY}/rules/branches/main")
    required = set(protection.get("contexts", ())) | {row["context"] for row in protection.get("checks", ())}
    for rule in rules:
        if rule["type"] == "required_status_checks":
            required.update(row["context"] for row in rule["parameters"]["required_status_checks"])
    require(required and required <= set(CHECK_WORKFLOWS), "required_checks_unavailable")
    checks = api.json(f"repos/{REPOSITORY}/commits/{head}/check-runs?per_page=100")
    require(checks["total_count"] <= 100, "check_pagination_required")
    observed = []
    for name in sorted(required):
        matches = [row for row in checks["check_runs"] if row["name"] == name and row["head_sha"] == head
                   and row["app"]["slug"] == "github-actions"]
        require(bool(matches), "required_check_missing")
        check = max(matches, key=lambda row: row["id"])
        require(check["status"] == "completed" and check["conclusion"] == "success", "required_check_missing")
        match = re.search(r"/actions/runs/([0-9]+)/", check["details_url"])
        require(match is not None, "run_identity_invalid")
        run_id = int(match[1])
        authenticate_run(api, run_id, head=head, workflow=CHECK_WORKFLOWS[name])
        observed.append(dict(name=name, check_id=check["id"], run_id=run_id, outcome="passed"))
    return observed


def authenticate_publication(api, run_id, head):
    from phase_loop_runtime.supervised_contracts import V2_PUBLICATION_PINS
    authenticate_run(api, run_id, head=head, workflow=".github/workflows/supervised-contract-intake.yml")
    artifacts = api.json(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100")
    require(artifacts["total_count"] <= 100, "artifact_pagination_required")
    rows = [row for row in artifacts["artifacts"] if row["name"] == f"schema-publication-{run_id}" and not row["expired"]]
    require(len(rows) == 1 and rows[0]["size_in_bytes"] <= 16777216, "publication_artifact_missing")
    artifact = rows[0]
    raw = api.bytes(f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip")
    digest = sha256(raw).hexdigest()
    require(artifact["digest"] == "sha256:" + digest, "artifact_digest_invalid")
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        require(set(archive.namelist()) == {"schema-publication.json", "schema-wheel.xml"}, "publication_artifact_invalid")
        require(all(info.file_size <= 16777216 for info in archive.infolist()), "artifact_size_invalid")
        publication = strict_json(archive.read("schema-publication.json"))
        require(publication["contract"] is True and publication["hosted_head"] == head
                and str(publication["hosted_run_id"]) == str(run_id), "publication_noop")
        require(publication["v2_resources"] == {name: dict(sha256=values[0], blob=values[1]) for name, values in V2_PUBLICATION_PINS.items()}, "publication_inventory_invalid")
        cases = list(ET.fromstring(archive.read("schema-wheel.xml")).iter("testcase"))
        require(cases and all(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases), "installed_proof_invalid")
    return dict(run_id=run_id, artifact_id=artifact["id"], artifact_sha256=digest, contract=True, outcome="passed")


def authenticate_assessment(api, run_id, head, identity):
    """A later read-only assessment verifies the completed verifier artifact."""
    authenticate_run(api, run_id, head=head, workflow=".github/workflows/supervised-v2-evidence.yml")
    artifacts = api.json(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100")
    require(artifacts["total_count"] <= 100, "artifact_pagination_required")
    rows = [row for row in artifacts["artifacts"] if row["name"] == f"supervised-v2-assessment-{run_id}" and not row["expired"]]
    require(len(rows) == 1 and rows[0]["size_in_bytes"] <= 16777216, "assessment_artifact_missing")
    artifact = rows[0]
    raw = api.bytes(f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip")
    digest = sha256(raw).hexdigest()
    require(artifact["digest"] == "sha256:" + digest, "artifact_digest_invalid")
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        require(archive.namelist() == ["supervised-v2-assessment.json"] and archive.infolist()[0].file_size <= 16777216,
                "assessment_artifact_invalid")
        assessment = strict_json(archive.read("supervised-v2-assessment.json"))
        require(assessment["assessment_runner"]["head"] == head
                and str(assessment["assessment_runner"]["run"]) == str(run_id)
                and assessment["content_identity"] == identity and assessment["byte_pin_authority"] is False,
                "assessment_identity_invalid")
    return dict(run_id=run_id, artifact_id=artifact["id"], artifact_sha256=digest, outcome="passed")


def evaluate(repo, record, *, api=None, current_head=None):
    result = verify_offline(repo, record)
    current_head = current_head or git(repo, "rev-parse", "HEAD").decode().strip()
    check_applicability(repo, record, current_head, api=api)
    result["content_identity"] = record["content_identity"]
    result["tested_head"] = record["tested_head"]
    result["assessed_head"] = current_head
    if api is None:
        result["hosted_status"] = "unverified"
        return result
    result["required_checks"] = authenticate_required_checks(api, current_head)
    def run_content_head(run_id):
        require(type(run_id) is int and run_id > 0, "run_identity_invalid")
        head = api.json(f"repos/{REPOSITORY}/actions/runs/{run_id}")["head_sha"]
        check_applicability(repo, record, head, api=api)
        return head
    publication = record.get("hosted_evidence", {}).get("publication_run_id")
    result["publication"] = authenticate_publication(api, publication, run_content_head(publication))
    gate = record.get("hosted_evidence", {}).get("gate_a_run_id")
    authenticate_run(api, gate, head=run_content_head(gate), workflow=".github/workflows/test.yml")
    jobs = api.json(f"repos/{REPOSITORY}/actions/runs/{gate}/jobs?per_page=100")
    require(jobs["total_count"] <= 100 and any(job["name"] == "clean-room (standalone-from-wheel, Gate A)"
            and job["conclusion"] == "success" for job in jobs["jobs"]), "gate_a_missing")
    artifacts = api.json(f"repos/{REPOSITORY}/actions/runs/{gate}/artifacts?per_page=100")
    require(artifacts["total_count"] <= 100, "artifact_pagination_required")
    rows = [row for row in artifacts["artifacts"] if row["name"] == "chronology-junit-gate-a" and not row["expired"]]
    require(len(rows) == 1 and rows[0]["size_in_bytes"] <= 16777216, "gate_a_artifact_missing")
    artifact = rows[0]
    raw = api.bytes(f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip")
    digest = sha256(raw).hexdigest()
    require(artifact["digest"] == "sha256:" + digest, "artifact_digest_invalid")
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        require(archive.namelist() == ["junit-gate-a.xml"] and archive.infolist()[0].file_size <= 16777216, "gate_a_artifact_invalid")
        cases = list(ET.fromstring(archive.read("junit-gate-a.xml")).iter("testcase"))
        require(cases and all(case.find("failure") is None and case.find("error") is None for case in cases)
                and any(case.find("skipped") is None for case in cases), "gate_a_not_passed")
    phase_cases = [case for case in cases if any(name in case.attrib.get("classname", "") for name in
                   ("test_supervised_contracts", "test_supervised_envelope_v2", "test_supervised_capture_v2", "test_supervised_v2_readiness"))]
    require(phase_cases and all(case.find("skipped") is None or case.attrib["name"].startswith("test_publication_change_selection[")
                               for case in phase_cases), "gate_a_phase_proof_missing")
    require({"test_module_and_installed_resource_origin", "test_v2_version_and_resource_pins"}
            <= {case.attrib["name"] for case in phase_cases if case.find("skipped") is None}, "installed_proof_invalid")
    result["gate_a"] = dict(run_id=gate, artifact_id=artifact["id"], artifact_sha256=digest, outcome="passed")
    result["hosted_status"] = "ci_and_publication_verified"
    verifier = record.get("hosted_evidence", {}).get("verifier_run_id")
    if verifier is not None:
        result["verifier"] = authenticate_assessment(api, verifier, run_content_head(verifier), record["content_identity"])
    else:
        result["hosted_status"] = "verifier_artifact_pending"
    # The pinned revision establishes no external publisher trust roots.
    # Authenticated CI cannot substitute for those producer-owned bindings.
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authenticate", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate(args.repo, read_receipt(args.receipt or args.repo / RECEIPT), api=GitHubEvidence() if args.authenticate else None)
    except (EvidenceRefused, OSError, ValueError, TypeError, KeyError, RecursionError, ET.ParseError) as error:
        result = dict(verification_status="blocked", byte_pin_authority=False, blocker_class="upstream_phase_unmet",
                      human_required=False, refusal=str(error) if isinstance(error, EvidenceRefused) else "evidence_invalid")
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
