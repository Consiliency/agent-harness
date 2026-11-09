"""Stamp fresh synthetic receipts while preserving their observations."""
import copy
import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/stamp_evidence_receipt.py"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="repository script absent in wheel")


def test_stamp_roundtrip_and_stale_binding(tmp_path):
    spec = importlib.util.spec_from_file_location("receipt_stamper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sources = {"fixture/producer.py": b"synthetic producer\n", "fixture/control.json": b'{"fixture":true}\n'}
    for relative, data in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    hashes = {relative: sha256(data).hexdigest() for relative, data in sources.items()}
    record = dict(schema="agent-harness.synthetic-stamp-test.v1", authority="synthetic_fixture_only",
        producer_outcomes={"synthetic-control": "passed"}, byte_pin_authority=False,
        source_hashes=hashes, runner_stamp=dict(observed_utc="2026-11-09T00:00:00Z",
            source_tree_digest=sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()))
    original = copy.deepcopy(record)
    receipt = tmp_path / "receipt.md"
    receipt.write_text("# Synthetic stamp fixture\n\n```json\n" + json.dumps(record, indent=2) + "\n```\n")
    before = receipt.read_text()
    pinned = tmp_path / next(iter(record["source_hashes"]))
    pinned.write_bytes(pinned.read_bytes() + b"\n")
    module.stamp(receipt, repo=tmp_path)
    stamped = json.loads(receipt.read_text().split("```json\n", 1)[1].split("\n```", 1)[0])
    def validate_bindings():
        assert stamped["source_hashes"] == {relative: sha256((tmp_path / relative).read_bytes()).hexdigest() for relative in sources}
    validate_bindings()
    for key in set(original) - {"source_hashes", "runner_stamp"}:
        assert stamped[key] == original[key]
    digest = sha256(json.dumps(stamped["source_hashes"], sort_keys=True).encode()).hexdigest()
    assert stamped["runner_stamp"] == {**original["runner_stamp"], "source_tree_digest": digest}
    hash_keys = set(original["source_hashes"]) | {"source_tree_digest"}
    def without_hash_lines(text):
        return [line for line in text.splitlines(keepends=True)
                if not any(line.lstrip().startswith(json.dumps(key) + ": ") for key in hash_keys)]
    assert set(stamped["source_hashes"]) == set(original["source_hashes"])
    assert without_hash_lines(receipt.read_text()) == without_hash_lines(before)
    first = receipt.read_bytes()
    module.stamp(receipt, repo=tmp_path)
    assert receipt.read_bytes() == first
    pinned.write_bytes(pinned.read_bytes() + b"changed")
    with pytest.raises(AssertionError):
        validate_bindings()
    pinned.unlink()
    with pytest.raises(FileNotFoundError):
        module.stamp(receipt, repo=tmp_path)
    assert receipt.read_bytes() == first
