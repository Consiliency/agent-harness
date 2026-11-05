"""Production API witnesses and independent frozen-publication comparisons."""
from dataclasses import FrozenInstanceError
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace

import pytest

import phase_loop_runtime.supervised_contracts as production
from phase_loop_runtime.supervised_contracts import ContractError, load_contract_bundle, validate_record

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "plans/artifacts/v12-SCHEMA-inputs.md"
WORKFLOW = ROOT / ".github/workflows/supervised-contract-intake.yml"
# Gate A deliberately omits the repository manifest and supplies its bytes by path.
SOURCE_MANIFEST = Path(os.environ.get("PHASE_LOOP_LEGIBLE_AUTHORITY_MANIFEST", ROOT / "plans/manifest.json"))
MANIFEST_ANCHOR = "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285"
COMMIT_ANCHOR = "93db4b4fcc4e3d40c62f6658b6a67b519c750491"


def anchor(module=production):
    data = INPUT.read_bytes()
    seal = next(r for r in json.loads(SOURCE_MANIFEST.read_bytes())["plans"] if r["slug"] == "v12-SCHEMA")["frozen_inputs"]["plans/artifacts/v12-SCHEMA-inputs.md"]["sha256"]
    assert sha256(data).hexdigest() == seal == module.INPUT_ARTIFACT_SHA256
    expected = {n: (d, b) for n, d, b in re.findall(
        r"^\| `([^`]+)` \| `([0-9a-f]{64})` \| `([0-9a-f]{40})` \|$", data.decode(), re.M)}
    assert len(expected) == 7
    assert dict(module.PUBLICATION_PINS) == expected
    assert module.PUBLICATION_PINS["conformance/SHA256SUMS"][0] == MANIFEST_ANCHOR
    commit = re.search(r"Source: public Consiliency/consiliency-contract, commit\n`([0-9a-f]{40})`", data.decode())
    assert commit and commit[1] == module.SOURCE_COMMIT == COMMIT_ANCHOR
    bundle = module.load_contract_bundle()
    for name, (digest, _) in expected.items():
        if name != "provenance.json":
            assert sha256(bundle.resource_bytes(name)).hexdigest() == digest
    return bundle


def isolated_module(tmp_path, transform=lambda text: text):
    """Copy only this production seam and its pinned resources, not the repository."""
    source = Path(production.__file__)
    target = tmp_path / "supervised_contracts.py"
    target.write_text(transform(source.read_text()))
    shutil.copytree(source.parent / "schemas/supervised-worker-v1", tmp_path / "schemas/supervised-worker-v1")
    spec = importlib.util.spec_from_file_location("schema_copy_" + str(abs(hash(str(tmp_path)))), target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Private source-copy resource origin. There is no production injection API.
    class CopyResources:
        @staticmethod
        def files(package):
            assert package == "phase_loop_runtime"
            return tmp_path
    module.resources = CopyResources
    return module


def test_frozen_input_and_production_pins():
    anchor()


def test_immutable_captured_buffers():
    bundle = anchor()
    name = "admitted-launch-envelope.schema.json"
    data = bundle.resource_bytes(name)
    assert type(data) is bytes and bundle.resource_bytes(name) is data
    with pytest.raises((FrozenInstanceError, AttributeError)):
        bundle._captured = ()
    with pytest.raises(TypeError):
        production.ContractBundle(())


@pytest.mark.parametrize("name", production._NAMES)
@pytest.mark.parametrize("mode", ["missing", "altered"])
def test_resources_fail_closed(tmp_path, name, mode):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()  # enter the unchanged production path first
    target = tmp_path / "schemas/supervised-worker-v1" / name
    if mode == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(module.ContractError) as caught:
        module.load_contract_bundle()
    assert caught.value.code == ("resource_missing" if mode == "missing" else "digest_mismatch")
    assert caught.value.resource == name
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_single_read_same_buffer(tmp_path):
    module = isolated_module(tmp_path)
    original = tmp_path / "schemas/supervised-worker-v1"
    reads = {}
    class Resource:
        def __init__(self, path):
            self.path = path
        def joinpath(self, *names):
            return Resource(self.path.joinpath(*names))
        @property
        def name(self):
            return self.path.name
        def iterdir(self):
            return (Resource(p) for p in self.path.iterdir())
        def is_dir(self):
            return self.path.is_dir()
        def is_file(self):
            return self.path.is_file()
        def read_bytes(self):
            reads[self.path] = reads.get(self.path, 0) + 1
            assert reads[self.path] == 1
            data = self.path.read_bytes()
            self.path.write_bytes(b"SENTINEL changed after capture")
            return data
    module.resources = type("Resources", (), {"files": staticmethod(lambda _: Resource(tmp_path))})
    bundle = module.load_contract_bundle()
    assert len(reads) == 7
    assert bundle.resource_bytes("admitted-launch-envelope.schema.json").startswith(b"{")
    assert all((original / name).read_bytes().startswith(b"SENTINEL") for name in module._NAMES)


@pytest.mark.parametrize("name", ["../provenance.json", "provenance.json", "https://example.invalid/s", "SENTINEL", None, []])
def test_resource_allowlist(name):
    with pytest.raises(ContractError) as caught:
        load_contract_bundle().resource_bytes(name)
    assert str(caught.value) == "resource_unlisted" and caught.value.resource is None


@pytest.mark.parametrize("family,definition", [("SENTINEL", None), ("admitted_launch_envelope.v1", "journal_line"),
    ("supervised_run_status.v1", "sha256"), ("supervised_run_status.v1", "SENTINEL"), ([], None), ("supervised_run_status.v1", [])])
def test_selector_refusal(family, definition):
    with pytest.raises(ContractError) as caught:
        validate_record(load_contract_bundle(), family, b"{}", definition=definition)
    assert str(caught.value) == "selector_invalid"


@pytest.mark.parametrize("data", [b'{"SENTINEL":1,"SENTINEL":2}', b'{"SENTINEL":NaN}', b'{"SENTINEL":Infinity}',
    b'{"SENTINEL":-Infinity}', b'{"SENTINEL":1e9999}', b'{"SENTINEL":9007199254740992}',
    b'{"SENTINEL":-9007199254740992}', b'{"SENTINEL":', b'\xff', {}, "SENTINEL",
    bytearray(b'{}'), b'{"SENTINEL":"\\ud800"}', b'{"\\udfff":1}', b'[' * 2000 + b']' * 2000])
def test_strict_record_intake(data):
    with pytest.raises(ContractError) as caught:
        validate_record(load_contract_bundle(), "admitted_launch_envelope.v1", data)
    assert str(caught.value) == "record_json_invalid"
    assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.mark.parametrize("text", ["0.5", "1.0", "1e2", "-0.25", "1e-9999", "9007199254740991.1", "9007199254740991", "-9007199254740991"])
def test_finite_numbers_preserve_types(text):
    bundle = load_contract_bundle()
    envelope = json.loads(bundle.resource_bytes("conformance/envelope.vectors.json"))["cases"][0]["input"]["envelope"]
    raw = json.dumps(envelope).replace('"caller_context": {', '"caller_context": {"finite": ' + text + ', ', 1).encode()
    validate_record(bundle, "admitted_launch_envelope.v1", raw)
    request = ('{"assignment_digest":"' + 'a' * 64 + '","page_size":' + text + ',"cursor":null}').encode()
    from decimal import Decimal
    if Decimal(text) == Decimal(text).to_integral_value():
        validate_record(bundle, "supervised_run_status.v1", request, definition="page_request")
    else:
        with pytest.raises(ContractError, match="record_schema_invalid"):
            validate_record(bundle, "supervised_run_status.v1", request, definition="page_request")


def repin(module, tmp_path, name, data):
    path = tmp_path / "schemas/supervised-worker-v1" / name
    path.write_bytes(data)
    pins = dict(module.PUBLICATION_PINS)
    pins[name] = (sha256(data).hexdigest(), pins[name][1])
    module.PUBLICATION_PINS = pins


@pytest.mark.parametrize("data", [b'{"x":0,"x":1}', b'{"x":NaN}', b'{"x":9007199254740992}'])
def test_resource_strict_json(tmp_path, data):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    repin(module, tmp_path, "conformance/envelope.vectors.json", data)
    with pytest.raises(module.ContractError, match="resource_json_invalid"):
        module.load_contract_bundle()


def test_runtime_support_refusal(tmp_path):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    module.metadata = type("Metadata", (), {"version": staticmethod(lambda _: "4.17.9"), "PackageNotFoundError": production.metadata.PackageNotFoundError})
    module._cached_schema_runtime.cache_clear()
    with pytest.raises(module.ContractError) as caught:
        module.load_contract_bundle()
    assert str(caught.value) == "runtime_unsupported" and caught.value.__context__ is None


def sync_copy_metadata(module, tmp_path):
    root = tmp_path / "schemas/supervised-worker-v1"
    manifest = "".join(module.PUBLICATION_PINS[n][0] + "  " +
        (n.removeprefix("conformance/") if n.startswith("conformance/") else "../" + n) + "\n"
        for n in module._UPSTREAM if n != "conformance/SHA256SUMS").encode()
    repin(module, tmp_path, "conformance/SHA256SUMS", manifest)
    provenance = json.loads((root / "harness-provenance.json").read_bytes())
    provenance["upstream_resources"] = {n: {"sha256": module.PUBLICATION_PINS[n][0], "blob": module.PUBLICATION_PINS[n][1]} for n in module._UPSTREAM}
    data = json.dumps(provenance).encode()
    (root / "harness-provenance.json").write_bytes(data)
    module._PROVENANCE_SHA256 = sha256(data).hexdigest()


def test_schema_invalid_closed_error(tmp_path):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    name = "run-status.schema.json"
    schema = json.loads(module.load_contract_bundle().resource_bytes(name))
    schema["$defs"]["units"]["type"] = "SENTINEL"
    repin(module, tmp_path, name, json.dumps(schema).encode())
    sync_copy_metadata(module, tmp_path)
    with pytest.raises(module.ContractError) as caught:
        module.load_contract_bundle()
    assert str(caught.value) == "schema_invalid:run-status.schema.json"
    assert caught.value.__context__ is None


@pytest.mark.parametrize("kind", ["byte_pin_authority", "commit", "source_repository", "root", "upstream_resources",
    "excluded_metadata", "input_artifact_sha256", "manifest", "manifest-entry", "manifest-encoding"])
def test_metadata_integrity(tmp_path, kind):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    root = tmp_path / "schemas/supervised-worker-v1"
    if not kind.startswith("manifest"):
        path = root / "harness-provenance.json"
        data = json.loads(path.read_bytes()); data[kind] = "SENTINEL"
        raw = json.dumps(data).encode(); path.write_bytes(raw)
        module._PROVENANCE_SHA256 = sha256(raw).hexdigest()
    else:
        path = root / "conformance/SHA256SUMS"
        data = path.read_bytes()
        data = data * 2 if kind == "manifest" else (b'\xff' if kind == "manifest-encoding" else data.replace(b'../', b'./', 1))
        repin(module, tmp_path, "conformance/SHA256SUMS", data)
    with pytest.raises(module.ContractError, match="manifest_invalid"):
        module.load_contract_bundle()


def test_module_and_installed_resource_origin():
    bundle = anchor()
    # Hosted packaging job requires the extracted wheel rather than the checkout.
    import os
    expected = os.environ.get("SCHEMA_WHEEL_ROOT")
    if expected:
        assert Path(production.__file__).resolve().is_relative_to(Path(expected).resolve())
        assert not Path(production.__file__).resolve().is_relative_to(ROOT / "phase-loop-runtime/src")
    resource = production.resources.files("phase_loop_runtime").joinpath("schemas/supervised-worker-v1")
    assert Path(str(resource)).resolve().parent.parent == Path(production.__file__).resolve().parent
    assert resource.joinpath("conformance/SHA256SUMS").read_bytes() == bundle.resource_bytes("conformance/SHA256SUMS")


def test_publication_comparison_offline(tmp_path):
    spec = importlib.util.spec_from_file_location("publication_check", ROOT / "phase-loop-runtime/scripts/verify_supervised_contract_publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = anchor()
    blobs = dict(production.PUBLICATION_PINS)
    upstream = {n: bundle.resource_bytes(n) for n in production._UPSTREAM}
    # Excluded metadata is inventoried by bytes only in scratch, never vendored.
    module.compare_publication(upstream, {n: b for n, (_, b) in blobs.items()}, bundle, include_excluded=False)
    bad = dict(upstream)
    bad["run-status.schema.json"] += b" "
    with pytest.raises(ValueError, match="publication_mismatch"):
        module.compare_publication(bad, {n: b for n, (_, b) in blobs.items()}, bundle, include_excluded=False)
    wrong_blobs = {n: b for n, (_, b) in blobs.items()}
    wrong_blobs["run-status.schema.json"] = "0" * 40
    with pytest.raises(ValueError, match="publication_mismatch"):
        module.compare_publication(upstream, wrong_blobs, bundle, include_excluded=False)


def test_no_public_injection_surface():
    import inspect
    assert Path(production.__file__).name == "supervised_contracts.py"
    assert load_contract_bundle.__module__ == validate_record.__module__ == "phase_loop_runtime.supervised_contracts"
    assert str(inspect.signature(load_contract_bundle)) == "() -> 'ContractBundle'"
    assert list(inspect.signature(validate_record).parameters) == ["bundle", "family", "record", "definition"]


@pytest.mark.parametrize("name", ["UNLISTED", "conformance/UNLISTED", "nested/file"])
def test_packaged_resource_inventory(tmp_path, name):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    path = tmp_path / "schemas/supervised-worker-v1" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"SENTINEL")
    with pytest.raises(module.ContractError) as caught:
        module.load_contract_bundle()
    assert str(caught.value) == "resource_unlisted"
    assert caught.value.__context__ is None


@pytest.mark.parametrize("kind", ["none", "text", "object", "empty", "altered"])
def test_bundle_input_contract(kind):
    bundle = load_contract_bundle()
    captured = bundle._captured
    if kind == "none": bundle = None
    elif kind == "text": bundle = "SENTINEL"
    elif kind == "object": bundle = SimpleNamespace(_captured=captured)
    else:
        bundle = object.__new__(production.ContractBundle)
        if kind == "altered":
            object.__setattr__(bundle, "_captured", ((captured[0][0], b'{}'), *captured[1:]))
    with pytest.raises(ContractError) as caught:
        validate_record(bundle, "admitted_launch_envelope.v1", b'{}')
    assert str(caught.value) == "manifest_invalid" and caught.value.__context__ is None


def test_validation_runtime_diagnostic(tmp_path, monkeypatch):
    module = isolated_module(tmp_path)
    bundle = module.load_contract_bundle()
    def validator(*args, **kwargs):
        raise ValueError("SENTINEL")
    _, registry, schemas = module._schema_runtime(dict(bundle._captured))
    monkeypatch.setattr(module, "_schema_runtime", lambda _: (validator, registry, schemas))
    with pytest.raises(module.ContractError) as caught:
        module.validate_record(bundle, "admitted_launch_envelope.v1", b'{}')
    assert str(caught.value) == "record_schema_invalid:admitted-launch-envelope.schema.json"
    assert caught.value.__context__ is None


def test_schema_identity_contract(tmp_path):
    module = isolated_module(tmp_path)
    bundle = module.load_contract_bundle()
    name = "run-status.schema.json"
    schema = json.loads(bundle.resource_bytes(name))
    schema["$id"] = "urn:contract:other"
    repin(module, tmp_path, name, json.dumps(schema).encode())
    sync_copy_metadata(module, tmp_path)
    with pytest.raises(module.ContractError, match="^schema_invalid$"):
        module.load_contract_bundle()


def test_runtime_constructor_contract(tmp_path, monkeypatch):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    import jsonschema
    class UnavailableValidator:
        def __init__(self, *args, **kwargs):
            raise TypeError("SENTINEL")
    monkeypatch.setattr(jsonschema, "Draft202012Validator", UnavailableValidator)
    module._cached_schema_runtime.cache_clear()
    with pytest.raises(module.ContractError) as caught:
        module.load_contract_bundle()
    assert str(caught.value) == "runtime_unsupported" and caught.value.__context__ is None


def publication_module():
    spec = importlib.util.spec_from_file_location("publication_check", ROOT / "phase-loop-runtime/scripts/verify_supervised_contract_publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["baseline", "seal", "inventory", "commit"])
def test_publication_sealed_inputs(tmp_path, monkeypatch, kind):
    module = publication_module()
    for name, source in (("plans/manifest.json", SOURCE_MANIFEST), ("plans/artifacts/v12-SCHEMA-inputs.md", INPUT)):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
    module.verify_seal(tmp_path)
    if kind == "baseline":
        return
    if kind == "seal":
        path = tmp_path / "plans/artifacts/v12-SCHEMA-inputs.md"
        path.write_bytes(path.read_bytes() + b' ')
    elif kind == "inventory": monkeypatch.setattr(module, "MANIFEST_ANCHOR", "0" * 64)
    else: monkeypatch.setattr(module, "SOURCE_COMMIT", "0" * 40)
    with pytest.raises(ValueError, match="publication_mismatch"):
        module.verify_seal(tmp_path)


@pytest.mark.parametrize("condition", ["success", "seal", "private", "default", "protection", "ancestry", "head", "advance", "bytes", "environment"])
def test_publication_runner_offline(tmp_path, monkeypatch, condition):
    module = publication_module()
    bundle = anchor()
    upstream = {n: bundle.resource_bytes(n) for n in production._UPSTREAM}
    upstream["provenance.json"] = b'{}'
    pins = dict(production.PUBLICATION_PINS)
    pins["provenance.json"] = (sha256(b'{}').hexdigest(), pins["provenance.json"][1])
    monkeypatch.setattr(module, "PUBLICATION_PINS", pins)
    verified = []
    def verify_seal(repo):
        verified.append(repo)
        if condition == "seal": raise ValueError("publication_mismatch")
    monkeypatch.setattr(module, "verify_seal", verify_seal)
    head = "a" * 40
    reads = []
    def command(argv, **kwargs):
        if argv[:2] == ["gh", "api"]:
            if argv[2].endswith("/branches/main"):
                reads.append(True)
                observed = "b" * 40 if condition == "head" or (condition == "advance" and len(reads) == 1) else head
                return json.dumps({"protected": condition != "protection", "commit": {"sha": observed}}).encode()
            return json.dumps({"private": condition == "private", "default_branch": "other" if condition == "default" else "main"}).encode()
        if argv[1] == "clone": return b''
        if argv[1] == "merge-base":
            if condition == "ancestry": raise module.subprocess.CalledProcessError(1, argv)
            return b''
        if argv[1:] == ["rev-parse", "origin/main"]: return head.encode()
        name = argv[2].split(":core/supervised-run/", 1)[1]
        if argv[1] == "show": return upstream[name] + (b' ' if condition == "bytes" else b'')
        assert argv[1] == "rev-parse"
        return pins[name][1].encode()
    monkeypatch.setattr(module.subprocess, "check_output", command)
    output = tmp_path / "publication.json"
    monkeypatch.setattr(sys, "argv", ["publication", "--repo", str(ROOT), "--output", str(output)])
    for key, value in {"GITHUB_RUN_ID": "123", "GITHUB_JOB": "publication", "GITHUB_SHA": head}.items():
        monkeypatch.setenv(key, value)
    if condition == "environment": monkeypatch.delenv("GITHUB_RUN_ID")
    if condition in ("success", "advance"):
        module.main()
        assert json.loads(output.read_bytes())["outcome"] == "passed"
    else:
        with pytest.raises((ValueError, KeyError, module.subprocess.CalledProcessError)):
            module.main()
        assert not output.exists()
    assert verified == [ROOT]


@pytest.mark.skipif(not WORKFLOW.is_file(), reason="workflow is not in this checkout")
@pytest.mark.parametrize("changed,seal_changed,expected", [
    (["docs/guide.md"], False, False), (["plans/manifest.json"], False, False),
    (["plans/manifest.json"], True, True),
    (["phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/conformance/SHA256SUMS"], False, True),
    (["phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py"], False, True),
    (["phase-loop-runtime/tests/test_supervised_contracts.py"], False, True),
    (["phase-loop-runtime/scripts/verify_supervised_contract_publication.py"], False, True),
    (["plans/artifacts/v12-SCHEMA-inputs.md"], False, True),
    ([".github/workflows/supervised-contract-intake.yml"], False, True)])
def test_publication_change_selection(tmp_path, monkeypatch, changed, seal_changed, expected):
    workflow = WORKFLOW.read_text()
    assert '"phase-loop-runtime/pyproject.toml"' in workflow and '"phase-loop-runtime/MANIFEST.in"' in workflow
    assert "types: [opened, synchronize, reopened, edited]" in workflow
    import textwrap
    script = textwrap.dedent(workflow.split("python3 - <<'PY'\n", 1)[1].split("          PY\n", 1)[0])
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("BASE_SHA", "a" * 40)
    monkeypatch.setenv("HEAD_SHA", "b" * 40)
    def command(argv):
        if argv[1] == "diff": return ("\0".join(changed) + "\0").encode()
        assert argv[:2] == ["git", "show"]
        seal = "changed" if seal_changed and argv[2].startswith("b") else "same"
        return json.dumps({"plans": [{"slug": "v12-SCHEMA", "frozen_inputs": {"seal": seal}}]}).encode()
    import subprocess
    monkeypatch.setattr(subprocess, "check_output", command)
    exec(compile(script, "workflow-selection", "exec"), {})
    assert output.read_text() == "contract=" + str(expected).lower() + "\n"
