"""GOVLEAN EC-GOVLEAN-8 roadmap reseal falsifiers."""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from .govlean_freeze_receipt import govlean_api_available


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.roadmap_reseal", "reseal_roadmap"),
    reason="GOVLEAN roadmap-reseal capability absent",
)


ROOT = Path(__file__).resolve().parents[2]
ROADMAP_REL = Path("specs/phase-plans-v10.md")
ASSUMPTIONS_REL = Path("phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py")
SIDECAR_REL = Path("specs/roadmap-assumption-probes-v10.json")
FIXTURE_REL = Path("phase-loop-runtime/tests/fixtures/roadmap-assumption-probes-v10.json")


def _reseal_module():
    return importlib.import_module("phase_loop_runtime.roadmap_reseal")


def _reseal_fixture(repo: Path) -> Path:
    roadmap = repo / ROADMAP_REL
    roadmap.parent.mkdir(parents=True)
    roadmap.write_bytes((ROOT / ROADMAP_REL).read_bytes() + b"\n")
    for relative in (ASSUMPTIONS_REL, SIDECAR_REL, FIXTURE_REL):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    return roadmap


def _constant_digest(source: str) -> str:
    match = re.search(r'^CANONICAL_ROADMAP_SHA256 = "([0-9a-f]{64})"$', source, re.MULTILINE)
    assert match is not None, source
    return match.group(1)


def test_reseal_write_refreshes_every_seal_representation_from_one_roadmap_digest(tmp_path):
    reseal = _reseal_module()
    repo = tmp_path / "reseal-repo"
    roadmap = _reseal_fixture(repo)
    expected_digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()

    reseal.reseal_roadmap(repo, roadmap, write=True)

    assert _constant_digest((repo / ASSUMPTIONS_REL).read_text(encoding="utf-8")) == expected_digest
    sidecar = json.loads((repo / SIDECAR_REL).read_text(encoding="utf-8"))
    fixture = json.loads((repo / FIXTURE_REL).read_text(encoding="utf-8"))
    assert sidecar["roadmap_sha256"] == expected_digest
    assert fixture["roadmap_sha256"] == expected_digest
    assert (repo / SIDECAR_REL).read_bytes() == (repo / FIXTURE_REL).read_bytes()
    reseal.reseal_roadmap(repo, roadmap, write=False)


def test_reseal_cli_check_reports_drift_and_write_makes_the_same_fixture_clean(tmp_path):
    _reseal_module()
    repo = tmp_path / "reseal-cli-repo"
    roadmap = _reseal_fixture(repo)
    write = subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.roadmap_reseal",
            "--repo",
            str(repo),
            "--roadmap",
            str(ROADMAP_REL),
            "--write",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert write.returncode == 0, write.stdout + write.stderr
    clean = subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.roadmap_reseal",
            "--repo",
            str(repo),
            "--roadmap",
            str(ROADMAP_REL),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr

    roadmap.write_bytes(roadmap.read_bytes() + b"reseal drift\n")
    drift = subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.roadmap_reseal",
            "--repo",
            str(repo),
            "--roadmap",
            str(ROADMAP_REL),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert drift.returncode != 0


def test_existing_legible_compatibility_and_manifest_consume_the_one_canonical_digest_constant():
    _reseal_module()
    assumptions = (ROOT / ASSUMPTIONS_REL).read_text(encoding="utf-8")
    manifest = (ROOT / "phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py").read_text(encoding="utf-8")
    compatibility_test = (ROOT / "phase-loop-runtime/tests/test_legible_review_repairs.py").read_text(encoding="utf-8")
    canonical_digest = _constant_digest(assumptions)

    assert canonical_digest not in manifest
    assert "CANONICAL_ROADMAP_SHA256" in manifest
    assert "LEGIBLE_ROADMAP_SHA256 = roadmap_assumptions.CANONICAL_ROADMAP_SHA256" in compatibility_test
