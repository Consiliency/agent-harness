"""Run the ACTUAL canonical Consiliency/spec outside-agent corpus through our validator.

This is the test whose absence let agent-harness#371 ship: every prior
outside-agent test fed submissions *we* authored in *our* dialect, so a validator
that could not parse the real contract corpus still looked green. Here we load the
vendored canonical vectors (``conformance/_contract``, provenance in ``VENDOR.json``)
and drive them through the governed-pipeline ``outside-agent-validate`` core
(:func:`build_outside_agent_validation_verdict`) — the same entry point the CLI
uses — asserting the corpus's own ``expected_valid`` outcomes.

If our validator implements a different dialect than the pinned contract, THIS test
fails on the canonical *valid* vectors (they get rejected), which is exactly the
divergence #371 reproduced.
"""
from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path

import pytest

from phase_loop_runtime.conformance.outside_agent_core import OutsideAgentVerdictStatus
from phase_loop_runtime.conformance.outside_agent_real import (
    OutsideAgentValidationExitCode,
    build_outside_agent_validation_verdict,
)

CONTRACT_ROOT = Path(str(resources.files("phase_loop_runtime.conformance") / "_contract"))
VENDOR_PATH = CONTRACT_ROOT / "VENDOR.json"
MANIFEST_PATH = CONTRACT_ROOT / "test-vectors" / "outside-agent" / "manifest.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_entries() -> list[dict]:
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["manifest_schema_version"] == "outside_agent_vector_manifest.v0.1"
    entries = manifest["vectors"]
    assert entries, "canonical manifest must not be empty"
    return entries


def _submission_entries() -> list[dict]:
    return [
        entry
        for entry in _manifest_entries()
        if entry["schema_target"] == "outside_agent_submission.v0.1"
    ]


def test_vendored_corpus_matches_recorded_digests() -> None:
    """Drift guard: a silently-mutated vendored copy recreates #371."""
    vendor = _load_json(VENDOR_PATH)
    assert vendor["source_repo"] == "Consiliency/spec"
    assert vendor["source_commit"], "vendor record must pin a source commit"
    recorded = vendor["files"]
    assert recorded, "vendor record must enumerate vendored files"
    for rel, expected in recorded.items():
        blob = (CONTRACT_ROOT / rel).read_bytes()
        actual = "sha256:" + hashlib.sha256(blob).hexdigest()
        assert actual == expected, f"vendored {rel} drifted from recorded digest"
    # Every vendored file must be recorded (no un-tracked drift surface). This
    # enumerates ALL vendored files, not just ``*.json``: the vendored spec oracle
    # (``oracle/outside_agent_router.py``) is executable code whose silent drift
    # would be exactly as dangerous as a mutated vector, so it must be digest-pinned
    # here too. Only ``VENDOR.json`` itself and bytecode caches are excluded.
    on_disk = {
        p.relative_to(CONTRACT_ROOT).as_posix()
        for p in CONTRACT_ROOT.rglob("*")
        if p.is_file()
        and p.name != "VENDOR.json"
        and "__pycache__" not in p.parts
    }
    assert on_disk == set(recorded), "vendored files and VENDOR.json record disagree"


@pytest.mark.parametrize(
    "entry",
    _submission_entries(),
    ids=[entry["case_id"] for entry in _submission_entries()],
)
def test_canonical_submission_vectors_route_through_validate(entry: dict) -> None:
    payload = _load_json(CONTRACT_ROOT / entry["path"])
    verdict = build_outside_agent_validation_verdict(payload)

    if entry["expected_valid"]:
        assert verdict.verdict.status == OutsideAgentVerdictStatus.PASS, (
            f"{entry['case_id']}: canonical VALID vector rejected — "
            f"blockers={[(b.code, b.ref) for b in verdict.verdict.blockers]}"
        )
        assert verdict.exit_code == OutsideAgentValidationExitCode.PASS
    else:
        assert verdict.verdict.status == OutsideAgentVerdictStatus.BLOCKED, (
            f"{entry['case_id']}: canonical INVALID vector accepted"
        )
        assert verdict.exit_code != OutsideAgentValidationExitCode.PASS
