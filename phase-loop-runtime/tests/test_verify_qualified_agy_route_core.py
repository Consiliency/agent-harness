"""`verify_qualified_agy_image.py --route-core` (agent-harness#1029).

Pull requests check only the qualified route's core files; the full pin set is enforced at
release. These pin both directions: a non-core drift passes route-core but still fails the
full check, and a route-core drift fails route-core.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
RECORDS = Path(__file__).resolve().parents[2] / "plans" / "evidence" / "qualified-provider-images.json"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or not RECORDS.is_file(),
    reason="the verifier and its evidence are repository source, absent from the standalone layout",
)


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _drift(verifier, monkeypatch, name):
    record, _ = verifier.validate_record(verify_sources=False)
    drifted = dict(record["source_sha256"])
    drifted[name] = "0" * 64
    monkeypatch.setattr(verifier, "actual_source_hashes", lambda: drifted)


def test_the_route_core_is_pinned_by_the_record(verifier):
    record, _ = verifier.validate_record(verify_sources=False)
    assert set(verifier.ROUTE_CORE) <= set(record["source_sha256"])


def test_a_non_core_drift_passes_route_core_but_fails_the_release_check(verifier, monkeypatch):
    _drift(verifier, monkeypatch, "president_operation.py")
    verifier.validate_record(route_core_only=True)
    with pytest.raises(ValueError, match="differ from this checkout"):
        verifier.validate_record()


@pytest.mark.parametrize("name", ["gemini_heartbeat.py", "qualify_gemini_heartbeat.py"])
def test_a_route_core_drift_fails_route_core(verifier, monkeypatch, name):
    _drift(verifier, monkeypatch, name)
    with pytest.raises(ValueError, match=f"route-core file {name}"):
        verifier.validate_record(route_core_only=True)
