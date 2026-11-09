"""Receipt stamping preserves observations and uses existing receipt validators."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest
import test_supervised_launch_receipt as envelope

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/stamp_evidence_receipt.py"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="repository script absent in wheel")


def test_stamp_roundtrip_and_stale_binding(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("receipt_stamper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    record = envelope.read_receipt(envelope.RECEIPT)
    original = copy.deepcopy(record)
    for relative in record["source_hashes"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((envelope.REPO / relative).read_bytes())
    receipt = tmp_path / "receipt.md"
    receipt.write_text("```json\n" + json.dumps(record, indent=2) + "\n```\n")
    pinned = tmp_path / next(iter(record["source_hashes"]))
    pinned.write_bytes(pinned.read_bytes() + b"\n")
    module.stamp(receipt, repo=tmp_path)
    monkeypatch.setattr(envelope, "REPO", tmp_path)
    stamped = envelope.read_receipt(receipt)
    envelope.validate_receipt(stamped)
    for key in set(original) - {"source_hashes", "runner_stamp"}:
        assert stamped[key] == original[key]
    assert stamped["runner_stamp"]["observed_utc"] == original["runner_stamp"]["observed_utc"]
    first = receipt.read_bytes()
    module.stamp(receipt, repo=tmp_path)
    assert receipt.read_bytes() == first
    pinned.write_bytes(pinned.read_bytes() + b"changed")
    with pytest.raises(AssertionError):
        envelope.validate_receipt(stamped)
    pinned.unlink()
    with pytest.raises(FileNotFoundError):
        module.stamp(receipt, repo=tmp_path)
    assert receipt.read_bytes() == first
