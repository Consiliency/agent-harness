"""The closed set of qualified agy entry images (agent-harness#1008; AGYROLL §3.1).

The runtime admits exactly the members of ``gemini_heartbeat.QUALIFIED_IMAGES``, which loads
from the shipped data catalog. Each member must have its own v2 qualification record, so the
set cannot be widened without a record. Membership is data, not code: this test pins no
version, so adding or ageing a member edits only ``data/agy_catalog.json`` and the records.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from phase_loop_runtime import gemini_heartbeat as gh

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "plans" / "evidence"
DATA = Path(gh.__file__).resolve().parent / "data" / "agy_catalog.json"

needs_repo = pytest.mark.skipif(not EVIDENCE.is_dir(), reason="the evidence records are repository source")


def _members():
    return gh.parse_catalog(DATA.read_text())


def test_the_runtime_set_is_exactly_the_data_file():
    assert gh.QUALIFIED_IMAGES == {m["image_sha256"]: m["help_sha256"] for m in _members()}
    assert gh.QUALIFIED_IMAGES, "the shipped catalog must not be empty"


@needs_repo
def test_every_member_has_its_own_v2_record_that_agrees():
    for member in _members():
        record = json.loads((EVIDENCE / member["record"]).read_text())
        assert record["schema"] == "agy_redacted_qualification_summary.v2"
        assert (record["release_version"], record["image_sha256"], record["help_sha256"],
                record["upstream_asset_sha256"], record["qci"]) == (
            member["release_version"], member["image_sha256"], member["help_sha256"],
            member["asset_sha256"], member["qci"])


@needs_repo
def test_the_old_evidence_catalog_is_gone():
    assert not (EVIDENCE / "qualified-provider-images.json").exists()


def test_the_runtime_module_holds_no_image_literal():
    """Adding a member never edits a route-core file again (AGYROLL §3.1 "Effect")."""
    source = Path(gh.__file__).read_text()
    for member in _members():
        assert member["image_sha256"] not in source and member["help_sha256"] not in source
