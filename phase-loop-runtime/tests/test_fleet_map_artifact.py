from __future__ import annotations

import copy
from importlib.resources import files
import json
import socket

import pytest
from jsonschema import Draft202012Validator

from phase_loop_runtime.cli import main
from phase_loop_runtime.fleet_map import build_fleet_map
from phase_loop_runtime.fleet_map_artifact import ArtifactError, build_artifact

PRODUCER = "1" * 40
PIN = "a" * 40
HEAD = "b" * 40
TIME = "2026-01-01T00:00:00Z"


@pytest.fixture
def fleet(tmp_path):
    root = tmp_path.resolve()
    rows = []
    for number, name in enumerate(("Example/source", "Example/target", "Other/target"), 1):
        path = root / str(number)
        path.mkdir()
        rows.append({"full_name": name, "github_repository_id": number,
                     "default_branch": "main", "head_sha": HEAD, "scan_state": "scanned", "local_path": str(number)})
    manifest = {"schema": "fleet_scan_input.v1", "clone_root": str(root),
                "scope": {"enumeration_complete": True, "expected_repos": 3, "accounts": [
                    {"login": "Example", "type": "Organization", "installation_id": 10, "repository_selection": "all", "enumerated_count": 2},
                    {"login": "Other", "type": "User", "installation_id": 20, "repository_selection": "selected", "enumerated_count": 1}]},
                "repositories": rows, "pin_observations": []}
    return root, manifest


def put(root, repo, relative, content):
    path = root / str(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def pin(root, **fields):
    return put(root, 1, "tools/agent-harness.pin.json", json.dumps({"repo": "Example/target", **fields}))


def artifact(fleet):
    return build_artifact(fleet[1], PRODUCER, TIME)


def observation(manifest, **overrides):
    item = {"from": "Example/source", "evidence_path": "tools/agent-harness.pin.json:1",
            "to": "Example/target", "effective_ref": PIN, "resolved_pin_sha": PIN,
            "target_head_sha": HEAD, "relation": "ancestor"}
    manifest["pin_observations"] = [{**item, **overrides}]


def test_actual_cli_produces_deterministic_closed_artifact(fleet, tmp_path, capsys, monkeypatch):
    root, manifest = fleet
    pin(root, sha=PIN)
    observation(manifest)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("offline command made a request"))
    path = tmp_path / "input.json"
    output = tmp_path / "output.json"
    path.write_text(json.dumps(manifest))
    argv = ["fleet-map", "--manifest", str(path), "--producer-commit", PRODUCER,
            "--generated-at", TIME, "--output", str(output)]
    assert main(argv) == 0
    first = output.read_bytes()
    assert main(argv) == 0
    assert output.read_bytes() == first
    result = json.loads(first)
    assert result["schema"] == "fleet_map.v1"
    assert result["source_commit"] == PRODUCER
    assert result["scanned_repos"] == ["Example/source", "Example/target", "Other/target"]
    assert result["edges"][0]["comparison"] == "behind"
    assert str(root).encode() not in first
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("args", [["--manifest", "input.json"], ["--output", "output.json"]])
def test_cli_requires_complete_artifact_mode(args, capsys):
    assert main(["fleet-map", *args]) == 2
    assert "requires" in capsys.readouterr().err


def test_cli_invalid_input_preserves_existing_output(fleet, tmp_path, capsys):
    source = tmp_path / "input.json"
    output = tmp_path / "output.json"
    source.write_text('{"unexpected":"sample-value"}')
    output.write_text("previous")
    assert main(["fleet-map", "--manifest", str(source), "--producer-commit", PRODUCER,
                 "--generated-at", TIME, "--output", str(output)]) == 2
    assert output.read_text() == "previous"
    assert "sample-value" not in capsys.readouterr().err


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(extra=True),
    lambda m: m["scope"].update(enumeration_complete=False),
    lambda m: m["scope"].update(expected_repos=4),
    lambda m: m["scope"]["accounts"][0].update(enumerated_count=3),
    lambda m: m["repositories"][1].update(full_name="example/SOURCE"),
    lambda m: m["repositories"][1].update(github_repository_id=1),
    lambda m: m["repositories"][0].update(head_sha="short"),
    lambda m: m["repositories"][0].update(head_sha=HEAD + "\n"),
    lambda m: m["repositories"][0].update(full_name="Example/source\n"),
    lambda m: m["repositories"][0].update(local_path="../elsewhere"),
    lambda m: m["repositories"][0].update(local_path="/elsewhere"),
    lambda m: m["repositories"][0].update(local_path="1/../2"),
])
def test_manifest_boundary_rejects_inconsistent_inputs(fleet, mutation):
    manifest = copy.deepcopy(fleet[1])
    mutation(manifest)
    with pytest.raises(ArtifactError):
        build_artifact(manifest, PRODUCER, TIME)


@pytest.mark.parametrize("commit,time", [("short", TIME), (PRODUCER, "2026-01-01T00:00:00"), (PRODUCER, "invalid")])
def test_explicit_provenance_is_validated(fleet, commit, time):
    with pytest.raises(ArtifactError):
        build_artifact(fleet[1], commit, time)


def test_owner_identity_adapter_preserves_same_basename_inputs(fleet):
    root, _ = fleet
    result = build_fleet_map([root / "2", root / "3"], identity_adapter=lambda p: {"2": "Example/target", "3": "Other/target"}[p.name])
    assert result.repos == ("Example/target", "Other/target")


def test_host_targets_distinguish_ambiguous_unmatched_and_unique(fleet):
    root, _ = fleet
    put(root, 1, "script.py", 'a="/home/example/code/target/src"\nb="/home/example/code/absent/src"')
    result = artifact(fleet)
    assert {(e["to"], e["target_state"], e["target_hint"]) for e in result["edges"]} == {
        (None, "ambiguous", "target"), (None, "unmatched", "absent")}
    put(root, 2, "script.py", 'a="/home/example/code/source/src"')
    assert any(e["to"] == "Example/source" and e["target_state"] == "known" for e in artifact(fleet)["edges"])


def test_copied_drift_retains_each_pair_and_omits_equal_content(fleet):
    root, _ = fleet
    put(root, 1, "contracts/shared.json", '{"a":1}')
    put(root, 2, "contracts/shared.json", '{"a":2}')
    put(root, 2, "schemas/shared.json", '{"a":3}')
    put(root, 3, "contracts/shared.json", '{"a":1}')
    edges = artifact(fleet)["edges"]
    assert len(edges) == 4
    source = [e for e in edges if e["from"] == "Example/source"]
    assert len(source) == 2
    assert {e["paired_evidence_path"] for e in source} == {"contracts/shared.json:1", "schemas/shared.json:1"}
    assert all(e["kind"] == "copied-literal" and e["maturity_label"] == "hash-checked" for e in edges)


@pytest.mark.parametrize("kind", ["linked-file", "linked-directory", "invalid-text", "malformed-pin"])
def test_scan_outcomes_are_explicit_for_unsupported_inputs(fleet, tmp_path, kind):
    root, _ = fleet
    if kind.startswith("linked"):
        external = tmp_path / "outside.txt"
        external.write_text("sample-content")
        (root / "1" / "source.py").symlink_to(external if kind == "linked-file" else root / "2")
    elif kind == "invalid-text":
        (root / "1" / "source.py").write_bytes(b"\xff")
    else:
        put(root, 1, "tools/agent-harness.pin.json", "{")
    result = artifact(fleet)
    assert result["repositories"][0]["scan_state"] == "scan_failed"
    assert "Example/source" not in result["scanned_repos"]
    assert not result["edges"]


def test_scan_read_failure_withholds_all_local_findings(fleet, monkeypatch):
    import phase_loop_runtime.fleet_map_artifact as module
    root, _ = fleet
    pin(root, sha=PIN)
    original = module.os.open
    def controlled(path, flags, *args, **kwargs):
        if path == "agent-harness.pin.json":
            raise PermissionError
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(module.os, "open", controlled)
    assert artifact(fleet)["repositories"][0]["failure_code"] == "scan_failed"


def test_repository_path_and_cache_boundaries(fleet):
    root, manifest = fleet
    put(root, 1, ".git/config", "ignored")
    (root / "1" / ".git" / "ignored.py").symlink_to(root / "2")
    assert len(artifact(fleet)["scanned_repos"]) == 3
    (root / "alias").symlink_to(root / "1")
    manifest["repositories"][0]["local_path"] = "alias"
    with pytest.raises(ArtifactError):
        artifact(fleet)


@pytest.mark.parametrize("state,code", [("empty", "empty_repository"), ("clone_failed", "clone_failed"), ("budget_exhausted", "budget_exhausted")])
def test_collection_failures_remain_known_uncovered_targets(fleet, state, code):
    root, manifest = fleet
    pin(root, sha=PIN)
    manifest["repositories"][1].update(scan_state=state, failure_code=code, local_path=None, head_sha=None)
    result = artifact(fleet)
    assert "Example/target" not in result["scanned_repos"]
    assert result["edges"][0]["target_state"] == "known"
    assert result["edges"][0]["comparison"] == "unresolvable"


@pytest.mark.parametrize("fields,relation,expected", [
    ({"sha": HEAD}, None, "up_to_date"),
    ({"ref": HEAD}, None, "up_to_date"),
    ({"sha": PIN}, None, "unresolvable"),
    ({"ref": "v1"}, "ancestor", "behind"),
    ({"sha": PIN}, "off_default_branch", "off_default_branch"),
    ({"version": "1.0"}, None, "unresolvable"),
])
def test_pin_verdicts_require_bound_observations(fleet, fields, relation, expected):
    root, manifest = fleet
    pin(root, **fields)
    if relation:
        observation(manifest, effective_ref=fields.get("sha", fields.get("ref")), relation=relation)
    assert artifact(fleet)["edges"][0]["comparison"] == expected


@pytest.mark.parametrize("declared,expected", [(PIN, "behind"), (HEAD, "unresolvable"), (None, "unresolvable")])
def test_immutable_pin_and_declared_ref_must_agree(fleet, declared, expected):
    root, manifest = fleet
    pin(root, sha=PIN, ref="main")
    observation(manifest, declared_ref_sha=declared)
    assert artifact(fleet)["edges"][0]["comparison"] == expected


@pytest.mark.parametrize("overrides", [{"target_head_sha": PIN}, {"resolved_pin_sha": HEAD}, {"evidence_path": "other.json:1"}, {"from": "Other/target"}, {"to": "Unknown/repo"}, {"relation": "equal"}])
def test_observations_cannot_change_their_binding(fleet, overrides):
    root, manifest = fleet
    pin(root, sha=PIN)
    observation(manifest, **overrides)
    with pytest.raises(ArtifactError):
        artifact(fleet)


def test_producer_pin_and_script_pin_use_qualified_identity(fleet):
    root, _ = fleet
    put(root, 1, "tools/fleet-map-producer.pin.json", json.dumps({"schema": "fleet_map_producer.v1", "repo": "Example/target", "source_commit": HEAD,
        "version": "1.0", "wheel_url": "https://example.invalid/unused.whl", "wheel_sha256": "2" * 64}))
    put(root, 1, "bootstrap.sh", 'echo "git+https://github.com/Other/target.git@v1#subdirectory=runtime"')
    edges = artifact(fleet)["edges"]
    assert {(e["to"], e.get("pinned_ref")) for e in edges} == {("Example/target", HEAD), ("Other/target", "v1")}
    assert "unused.whl" not in json.dumps(edges)


@pytest.mark.parametrize("value", ["https://sample:sample-value@github.com/Example/target", "https://example.invalid/Example/target", "https://github.com/Example/target?sample=sample-value"])
def test_pin_locator_boundary_returns_only_scan_status(fleet, value):
    root, _ = fleet
    put(root, 1, "tools/agent-harness.pin.json", json.dumps({"repo": value}))
    result = artifact(fleet)
    assert result["repositories"][0]["scan_state"] == "scan_failed"
    assert "sample-value" not in json.dumps(result)


def test_schema_is_packaged_and_all_shapes_are_closed(fleet):
    schema = json.loads(files("phase_loop_runtime").joinpath("schemas/fleet_map.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert {"fleet_scan_input.v1", "fleet_map_source.v1"} <= set(schema["$defs"])
    result = artifact(fleet)
    result["extra"] = True
    assert not Draft202012Validator(schema).is_valid(result)


def test_manifest_order_does_not_change_artifact(fleet):
    root, manifest = fleet
    pin(root, sha=HEAD)
    first = artifact(fleet)
    manifest["repositories"].reverse()
    manifest["scope"]["accounts"].reverse()
    assert artifact(fleet) == first


@pytest.mark.parametrize("fields", [
    {"sha": "short"}, {"sha": PIN, "source_commit": HEAD},
    {"repo": "Other/target", "url": "https://github.com/Example/target"},
    {"ref": "main", "version": 1},
])
def test_pin_field_consistency_withholds_repository_coverage(fleet, fields):
    root, _ = fleet
    pin(root, **fields)
    assert "Example/source" not in artifact(fleet)["scanned_repos"]


def test_multiple_same_location_pin_declarations_are_checked(fleet):
    root, _ = fleet
    put(root, 1, "bootstrap.sh", "echo git+https://github.com/Example/target@v1 git+https://github.com/Example/target@v2")
    assert "Example/source" not in artifact(fleet)["scanned_repos"]


def test_duplicate_observations_are_rejected(fleet):
    root, manifest = fleet
    pin(root, sha=PIN)
    observation(manifest)
    manifest["pin_observations"].append(copy.deepcopy(manifest["pin_observations"][0]))
    with pytest.raises(ArtifactError):
        artifact(fleet)


def test_qualified_non_enumerated_target_is_outside_scope(fleet):
    root, _ = fleet
    pin(root, repo="Elsewhere/target", ref="v1")
    edge = artifact(fleet)["edges"][0]
    assert edge["to"] == "Elsewhere/target"
    assert edge["target_state"] == "outside_scope"
    assert edge["comparison"] == "unresolvable"


@pytest.mark.parametrize("locator", [False, True])
@pytest.mark.parametrize("declared", [PIN, HEAD])
def test_literal_ref_observations_preserve_declared_identity(fleet, locator, declared):
    root, manifest = fleet
    fields = {"url": f"https://github.com/Example/target@{declared}"} if locator else {"ref": declared}
    pin(root, sha=PIN, **fields)
    observation(manifest, declared_ref_sha=declared)
    expected = "behind" if declared == PIN else "unresolvable"
    assert artifact(fleet)["edges"][0]["comparison"] == expected
    if declared != PIN:
        observation(manifest, declared_ref_sha=PIN)
        with pytest.raises(ArtifactError):
            artifact(fleet)


@pytest.mark.parametrize("kind", ["ref", "url", "script", "sha", "source_commit"])
@pytest.mark.parametrize("target_head", [PIN, HEAD])
@pytest.mark.parametrize("declared", [None, PIN, HEAD])
def test_literal_only_declarations_bind_optional_observations(fleet, kind, target_head, declared):
    root, manifest = fleet
    evidence = "tools/agent-harness.pin.json:1"
    if kind == "script":
        put(root, 1, "bootstrap.sh", f'echo "git+https://github.com/Example/target@{PIN}"')
        evidence = "bootstrap.sh:1"
    elif kind == "url":
        pin(root, url=f"https://github.com/Example/target@{PIN}")
    else:
        pin(root, **{kind: PIN})
    manifest["repositories"][1]["head_sha"] = target_head
    assert artifact(fleet)["edges"][0]["comparison"] == ("up_to_date" if target_head == PIN else "unresolvable")
    observation(manifest, evidence_path=evidence, target_head_sha=target_head,
                relation="equal" if target_head == PIN else "ancestor", declared_ref_sha=declared)
    if declared not in (None, PIN):
        with pytest.raises(ArtifactError):
            artifact(fleet)
    else:
        assert artifact(fleet)["edges"][0]["comparison"] == ("up_to_date" if target_head == PIN else "behind")


def test_target_collection_state_is_independent_of_locator_kind(fleet):
    root, manifest = fleet
    manifest["repositories"][0].update(scan_state="clone_failed", failure_code="not_found_or_inaccessible", local_path=None, head_sha=None)
    put(root, 2, "script.py", 'x="/home/example/code/source/src"')
    put(root, 2, "tools/agent-harness.pin.json", json.dumps({"repo": "Example/source", "sha": PIN}))
    edges = artifact(fleet)["edges"]
    assert {edge["kind"] for edge in edges} == {"pin", "host-path"}
    assert all(edge["target_state"] == "not_found_or_inaccessible" for edge in edges)
    assert all(edge["maturity_label"] == "presence-only" for edge in edges)


@pytest.mark.parametrize("value", ["https://example.invalid/sample", "/sample/path", "main\n", "a\\b", "a..b", "a/", "a//b", ".hidden", "a/.hidden", "a.lock", "a.lock/b", "a@{b", "@", "-option", "a b", "x" * 257])
def test_branch_and_ref_schema_boundaries_preserve_cli_output(fleet, tmp_path, capsys, value):
    root, manifest = fleet
    schema = json.loads(files("phase_loop_runtime").joinpath("schemas/fleet_map.v1.schema.json").read_text())
    definitions = schema["$defs"]
    assert not Draft202012Validator({"$ref": "#/$defs/git_ref", "$defs": definitions}).is_valid(value)
    manifest["repositories"][0]["default_branch"] = value
    source, output = tmp_path / "input.json", tmp_path / "output.json"
    source.write_text(json.dumps(manifest))
    output.write_text("previous")
    assert main(["fleet-map", "--manifest", str(source), "--producer-commit", PRODUCER,
                 "--generated-at", TIME, "--output", str(output)]) == 2
    assert output.read_text() == "previous"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert value not in captured.err
    manifest["repositories"][0]["default_branch"] = "main"
    pin(root, ref=value)
    assert "Example/source" not in artifact(fleet)["scanned_repos"]


@pytest.mark.parametrize("value", ["main", "feature/map-v1", "v1.2.3", "équipe/carte"])
def test_supported_branch_refs_round_trip(fleet, value):
    root, manifest = fleet
    manifest["repositories"][0]["default_branch"] = value
    pin(root, ref=value)
    result = artifact(fleet)
    assert result["repositories"][0]["default_branch"] == value
    assert result["edges"][0]["pinned_ref"] == value


def test_unsupported_host_identity_is_repository_local(fleet):
    root, _ = fleet
    pin(root, sha=PIN)
    put(root, 1, "source.py", 'x="/home/example/code/café/src"')
    put(root, 2, "source.py", 'x="/home/example/code/absent/src"')
    result = artifact(fleet)
    assert result["scanned_repos"] == ["Example/target", "Other/target"]
    assert result["repositories"][0]["failure_code"] == "scan_failed"
    assert len(result["edges"]) == 1
    assert result["edges"][0]["target_hint"] == "absent"
    assert "café" not in json.dumps(result, ensure_ascii=False)


def test_directory_component_changes_keep_scan_boundary(fleet, tmp_path, monkeypatch):
    import phase_loop_runtime.fleet_map_artifact as module
    root, manifest = fleet
    parent = root / "nested"
    parent.mkdir()
    (root / "1").rename(parent / "repo")
    manifest["repositories"][0]["local_path"] = "nested/repo"
    outside = tmp_path / "outside"
    (outside / "repo").mkdir(parents=True)
    put(outside, "repo", "source.py", 'x="/home/example/code/absent/src"')
    original = module.build_fleet_map
    def changed(*args, **kwargs):
        parent.rename(root / "saved")
        parent.symlink_to(outside, target_is_directory=True)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "build_fleet_map", changed)
    result = artifact(fleet)
    assert result["repositories"][0]["failure_code"] == "scan_failed"
    assert result["scanned_repos"] == ["Example/target", "Other/target"]
    assert result["edges"] == []
