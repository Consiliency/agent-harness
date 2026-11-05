"""Production API witnesses and independent frozen-publication comparisons."""
from dataclasses import FrozenInstanceError
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import pytest

import phase_loop_runtime.supervised_contracts as production
from phase_loop_runtime.supervised_contracts import ContractError, load_contract_bundle, validate_record

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "plans/artifacts/v12-SCHEMA-inputs.md"
MANIFEST_ANCHOR = "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285"


def anchor(module=production):
    data = INPUT.read_bytes()
    seal = next(r for r in json.loads((ROOT / "plans/manifest.json").read_bytes())["plans"] if r["slug"] == "v12-SCHEMA")["frozen_inputs"]["plans/artifacts/v12-SCHEMA-inputs.md"]["sha256"]
    assert sha256(data).hexdigest() == seal == module.INPUT_ARTIFACT_SHA256
    expected = {n: (d, b) for n, d, b in re.findall(
        r"^\| `([^`]+)` \| `([0-9a-f]{64})` \| `([0-9a-f]{40})` \|$", data.decode(), re.M)}
    assert len(expected) == 7
    assert dict(module.PUBLICATION_PINS) == expected
    assert module.PUBLICATION_PINS["conformance/SHA256SUMS"][0] == MANIFEST_ANCHOR
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
    b'{"SENTINEL":-9007199254740992}', b'{"SENTINEL":', b'\xff', {}, "SENTINEL"])
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


@pytest.mark.parametrize("kind", ["provenance", "manifest"])
def test_metadata_integrity(tmp_path, kind):
    module = isolated_module(tmp_path)
    module.load_contract_bundle()
    root = tmp_path / "schemas/supervised-worker-v1"
    if kind == "provenance":
        path = root / "harness-provenance.json"
        data = json.loads(path.read_bytes()); data["byte_pin_authority"] = True
        raw = json.dumps(data).encode(); path.write_bytes(raw)
        module._PROVENANCE_SHA256 = sha256(raw).hexdigest()
    else:
        path = root / "conformance/SHA256SUMS"
        repin(module, tmp_path, "conformance/SHA256SUMS", path.read_bytes() * 2)
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
    assert str(inspect.signature(load_contract_bundle)) == "() -> 'ContractBundle'"
    assert list(inspect.signature(validate_record).parameters) == ["bundle", "family", "record", "definition"]
