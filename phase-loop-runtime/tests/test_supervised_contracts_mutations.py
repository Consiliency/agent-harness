"""Serial source-copy mutations with baseline assertions and path witnesses."""
from hashlib import sha256, sha1
import json
from pathlib import Path
import sys

import pytest

from test_supervised_contracts import anchor, isolated_module
from test_supervised_contracts_vectors import ENVELOPE, STATUS, encoded, examples, expand


def entered(module, assertion):
    calls = set()
    def trace(frame, event, arg):
        if event == "call" and frame.f_code.co_filename == module.__file__:
            calls.add(frame.f_code.co_name)
        return trace
    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        assertion(module)
    finally:
        sys.settrace(previous)
    assert "load_contract_bundle" in calls
    return calls


def digest_assertion(module):
    bundle = module.load_contract_bundle()
    assert bundle.resource_bytes("run-status.schema.json")
    root = Path(module.__file__).parent / "schemas/supervised-worker-v1"
    target = root / "run-status.schema.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(module.ContractError, match="digest_mismatch"):
        module.load_contract_bundle()


def validation_assertion(module):
    bundle = module.load_contract_bundle()
    with pytest.raises(module.ContractError, match="record_schema_invalid"):
        module.validate_record(bundle, ENVELOPE, b'{"sentinel":true}')


def pattern_assertion(module):
    bundle = module.load_contract_bundle()
    record = expand(ENVELOPE, "E-admitted")["envelope"]
    record["assignment_digest"] = "a" * 64 + "\n"
    with pytest.raises(module.ContractError, match="record_schema_invalid"):
        module.validate_record(bundle, ENVELOPE, encoded(record))


def selector_assertion(module):
    bundle = module.load_contract_bundle()
    with pytest.raises(module.ContractError, match="selector_invalid"):
        module.validate_record(bundle, STATUS, b"{}", definition="sha256")


def allowlist_assertion(module):
    bundle = module.load_contract_bundle()
    with pytest.raises(module.ContractError, match="resource_unlisted"):
        bundle.resource_bytes("provenance.json")


def captured_assertion(module):
    root = Path(module.__file__).parent
    class Once:
        def __init__(self, path): self.path = path
        def joinpath(self, *parts): return Once(self.path.joinpath(*parts))
        @property
        def name(self): return self.path.name
        def iterdir(self): return (Once(p) for p in self.path.iterdir())
        def is_dir(self): return self.path.is_dir()
        def is_file(self): return self.path.is_file()
        def read_bytes(self):
            data = self.path.read_bytes()
            self.path.write_bytes(b"not JSON after capture")
            return data
    module.resources = type("Resources", (), {"files": staticmethod(lambda _: Once(root))})
    assert module.load_contract_bundle().resource_bytes("run-status.schema.json").startswith(b"{")


CONTROLS = {
    "digest": ("if sha256(data).hexdigest() != expected:", "if False:", digest_assertion),
    "validation": ("failed = next(validator(schema, registry=registry).iter_errors(instance), None) is not None", "failed = False", validation_assertion),
    "pattern": ('expression = r"^[0-9a-f]{64}\\Z"', 'expression = r"^[0-9a-f]{64}$"', pattern_assertion),
    "selector": ('and (not isinstance(definition, str) or definition not in _DEFINITIONS)', 'and False', selector_assertion),
    "allowlist": ('if not isinstance(name, str) or name not in _NAMES:', 'if False:', allowlist_assertion),
    "captured-buffer": ('parsed = {n: _strict_json(b,', 'captured = {n: root.joinpath(n).read_bytes() for n in _NAMES}\n    parsed = {n: _strict_json(b,', captured_assertion),
}


@pytest.mark.parametrize("control", CONTROLS)
def test_production_control(tmp_path, control):
    old, new, assertion = CONTROLS[control]
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    calls = entered(isolated_module(baseline), assertion)
    if control in ("validation", "pattern", "selector"):
        assert "validate_record" in calls
    mutated = tmp_path / "mutated"
    mutated.mkdir()
    def transform(text):
        assert text.count(old) == 1
        return text.replace(old, new)
    module = isolated_module(mutated, transform)
    # A killed mutation is a baseline assertion that now fails, not a green
    # test-only reimplementation of the guard.
    with pytest.raises((AssertionError, pytest.fail.Exception, module.ContractError)):
        assertion(module)


@pytest.mark.parametrize("definition", ["journal_line", "projection", "page_request", "page", "reader_view"])
def test_every_definition_selector_control(tmp_path, definition):
    record = examples()[STATUS, definition]
    def assertion(module):
        bundle = module.load_contract_bundle()
        assert module.validate_record(bundle, STATUS, encoded(record), definition=definition) is None
    base = tmp_path / "baseline"; base.mkdir()
    assert "validate_record" in entered(isolated_module(base), assertion)
    mutant = tmp_path / "mutant"; mutant.mkdir()
    alternate = "page" if definition != "page" else "page_request"
    module = isolated_module(mutant, lambda text: text.replace('(definition or "journal_line")', repr(alternate)))
    with pytest.raises(module.ContractError, match="record_schema_invalid"):
        assertion(module)


def coherent_resources(module, root, *, external=False):
    """Rebuild the ENTIRE closure, manifest, metadata and private expected pins.

    The unchanged reviewed artifact remains an independent authority anchor.
    """
    root = root / "schemas/supervised-worker-v1"
    pins = dict(module.PUBLICATION_PINS)
    for name in module._UPSTREAM:
        if name == "conformance/SHA256SUMS":
            continue
        data = (root / name).read_bytes() + b"\n"
        if external and name == "run-status.schema.json":
            schema = json.loads(data)
            schema["$defs"]["journal_line"]["properties"]["attempt"] = {"$ref": "https://example.invalid/foreign"}
            data = encoded(schema)
        (root / name).write_bytes(data)
        blob = sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        pins[name] = (sha256(data).hexdigest(), blob)
    manifest = "".join(pins[n][0] + "  " + (n.removeprefix("conformance/") if n.startswith("conformance/") else "../" + n) + "\n"
                       for n in module._UPSTREAM if n != "conformance/SHA256SUMS").encode()
    (root / "conformance/SHA256SUMS").write_bytes(manifest)
    pins["conformance/SHA256SUMS"] = (sha256(manifest).hexdigest(), sha1(b"blob " + str(len(manifest)).encode() + b"\0" + manifest).hexdigest())
    provenance = json.loads((root / "harness-provenance.json").read_bytes())
    provenance["upstream_resources"] = {n: {"sha256": pins[n][0], "blob": pins[n][1]} for n in module._UPSTREAM}
    data = encoded(provenance)
    (root / "harness-provenance.json").write_bytes(data)
    # Rewrite source too: the model is a consistently regenerated distribution,
    # not merely a temporary inconsistent in-memory table.
    path = Path(module.__file__)
    text = path.read_text()
    for name, (old_digest, old_blob) in module.PUBLICATION_PINS.items():
        text = text.replace(old_digest, pins[name][0]).replace(old_blob, pins[name][1])
    text = text.replace(module._PROVENANCE_SHA256, sha256(data).hexdigest())
    path.write_text(text)
    module.PUBLICATION_PINS = pins
    module._PROVENANCE_SHA256 = sha256(data).hexdigest()


def test_reference_integrity_complete_repin(tmp_path):
    module = isolated_module(tmp_path)
    entered(module, anchor)
    coherent_resources(module, tmp_path)
    module.load_contract_bundle()  # coherent local resources still enter production
    with pytest.raises(AssertionError):
        anchor(module)


def test_offline_reference_control(tmp_path):
    base = tmp_path / "base"; base.mkdir()
    module = isolated_module(base)
    module.load_contract_bundle()
    coherent_resources(module, base, external=True)
    with pytest.raises(module.ContractError, match="reference_unlisted"):
        module.load_contract_bundle()
    mutant = tmp_path / "mutant"; mutant.mkdir()
    module = isolated_module(mutant, lambda text: text.replace('raise ContractError("reference_unlisted", name) from None', 'continue'))
    module.load_contract_bundle()
    coherent_resources(module, mutant, external=True)
    # Bypassing the early closure check makes the load refusal assertion fail.
    with pytest.raises(pytest.fail.Exception):
        with pytest.raises(module.ContractError, match="reference_unlisted"):
            module.load_contract_bundle()


@pytest.mark.parametrize("control", ["patch", "rehash"])
def test_vector_helper_control(tmp_path, control):
    import importlib.util
    import test_supervised_contracts_vectors as vectors
    value = vectors.expand(ENVELOPE, "RC16-stale-rehashed")
    assert value["envelope"]["envelope_digest"] == vectors.envelope_digest(value["envelope"])
    text = Path(vectors.__file__).read_text()
    if control == "patch":
        text = text.replace('parent[key] = deepcopy(operation["value"])', 'pass')
    else:
        text = text.replace('value["envelope"]["envelope_digest"] = envelope_digest(value["envelope"])', 'pass')
    path = tmp_path / "vector_copy.py"; path.write_text(text)
    spec = importlib.util.spec_from_file_location("vector_control_" + control, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with pytest.raises(AssertionError):
        module.expand(ENVELOPE, "RC16-stale-rehashed")
