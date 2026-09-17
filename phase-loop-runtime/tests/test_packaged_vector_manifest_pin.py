"""agent-harness#527 F4: the packaged corpus manifest is checked against the contract pin.

`_validate_manifest` compares `manifest_digest` only when the manifest carries that key, and the
packaged manifest does not, so the arm never fired on the production path. The contract pin already
records `vector_manifest_hash`. The runner now requires the packaged default manifest's raw-byte
SHA-256 to equal it. Explicitly supplied manifests keep their existing checks.

No node ID in this module contains the CONFORM lifecycle selector keyword, so it does not join that
frozen corpus.
"""

from __future__ import annotations

import dataclasses
import hashlib

from phase_loop_runtime.conformance import outside_agent_vectors as vectors
from phase_loop_runtime.conformance.outside_agent_core import OutsideAgentVerdictStatus
from phase_loop_runtime.conformance.outside_agent_pin import EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN as PIN

MANIFEST = "test-vectors/outside-agent/manifest.json"


def _manifest_blockers(results):
    return [b for r in results if r.vector_name == "__manifest__" for b in r.blockers]


def test_packaged_manifest_matches_the_pinned_hash():
    raw = vectors._contract_path(MANIFEST).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PIN.vector_manifest_hash


def test_packaged_corpus_still_runs_against_the_real_pin():
    results = vectors.run_outside_agent_vectors()
    assert _manifest_blockers(results) == []
    assert results and all(r.matched for r in results)


def test_packaged_manifest_drift_from_the_pin_is_blocked(tmp_path, monkeypatch):
    real = vectors._contract_path
    drifted = tmp_path / "manifest.json"
    drifted.write_bytes(real(MANIFEST).read_bytes() + b"\n")  # same JSON, different raw bytes

    def contract_path(relative):
        return drifted if relative == MANIFEST else real(relative)

    monkeypatch.setattr(vectors, "_contract_path", contract_path)
    results = vectors.run_outside_agent_vectors()

    assert len(results) == 1 and results[0].vector_name == "__manifest__"
    assert results[0].status == OutsideAgentVerdictStatus.BLOCKED
    assert [b.code for b in results[0].blockers] == ["digest_mismatch"]


def test_a_changed_pin_blocks_the_unchanged_packaged_manifest():
    wrong = dataclasses.replace(PIN, vector_manifest_hash="0" * 64)
    results = vectors.run_outside_agent_vectors(contract_pin=wrong)
    assert [b.code for b in _manifest_blockers(results)] == ["digest_mismatch"]


def test_explicit_manifests_keep_their_existing_checks(tmp_path):
    raw = vectors._contract_path(MANIFEST).read_bytes()
    explicit = tmp_path / "manifest.json"
    explicit.write_bytes(raw + b"\n")  # would drift from the pin, but explicit manifests are not pin-bound
    results = vectors.run_outside_agent_vectors(explicit)
    assert all(b.code != "digest_mismatch" for b in _manifest_blockers(results))
