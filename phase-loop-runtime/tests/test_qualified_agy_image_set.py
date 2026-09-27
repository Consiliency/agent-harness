"""The closed set of qualified agy entry images (agent-harness#1008).

The runtime admits exactly the members of ``gemini_heartbeat.QUALIFIED_IMAGES``. Each member
must have its own qualification record, listed in the evidence catalog, so the set cannot be
widened without a record, and the verifier checks every member's record.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from phase_loop_runtime import gemini_heartbeat as gh

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "plans" / "evidence"
CATALOG = EVIDENCE / "qualified-provider-images.json"

AGY_1211 = "ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56"
AGY_1212 = "ce6fdd9e7621ee9ac6eedaa337731ca1f235e412ff57cf9eabcd2aa23b3576ca"
HELP_1211_1212 = "83e3a0c36269f23972ba33d0013b9a6b2933ddb07cde268fa40e0fb1a5f33755"

needs_repo = pytest.mark.skipif(
    not SCRIPT.is_file() or not CATALOG.is_file(),
    reason="the verifier and its evidence are repository source, absent from the standalone layout",
)


def test_the_qualified_image_set_is_exactly_the_reviewed_members():
    """Golden: widening or narrowing the admitted set is a reviewed change to this test."""
    assert gh.QUALIFIED_IMAGES == {AGY_1211: HELP_1211_1212, AGY_1212: HELP_1211_1212}


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image_set", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_repo
def test_every_runtime_member_has_its_own_catalogued_record(verifier):
    records = verifier.validate_records(verify_sources=False)
    assert {(r["image_sha256"], r["help_sha256"]) for r in records} == set(gh.QUALIFIED_IMAGES.items())
    assert sorted(r["release_version"] for r in records) == ["1.2.11", "1.2.12"]


@needs_repo
def test_the_verifier_reads_the_runtime_literal_not_a_copy(verifier):
    assert verifier.image_constants()["QUALIFIED_IMAGES"] == gh.QUALIFIED_IMAGES


@pytest.fixture
def evidence(verifier, tmp_path, monkeypatch):
    """A private copy of the catalog and every member's record for the verifier to read."""
    if not CATALOG.is_file():
        pytest.skip("the evidence catalog is repository source")
    catalog = json.loads(CATALOG.read_text())
    for member in catalog["routes"]["gemini_heartbeat_linux_x64"]["images"]:
        shutil.copy(EVIDENCE / member["record"], tmp_path / member["record"])
    shutil.copy(CATALOG, tmp_path / CATALOG.name)
    monkeypatch.setattr(verifier, "EVIDENCE", tmp_path)
    return tmp_path


def _edit(path, change):
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def _members(value):
    return value["routes"]["gemini_heartbeat_linux_x64"]["images"]


@needs_repo
def test_the_private_copy_validates(verifier, evidence):
    assert len(verifier.validate_records(verify_sources=False)) == len(gh.QUALIFIED_IMAGES)


@needs_repo
def test_a_runtime_digest_without_a_catalogued_record_refuses(verifier, evidence, monkeypatch):
    widened = {**gh.QUALIFIED_IMAGES, "f" * 64: HELP_1211_1212}
    monkeypatch.setattr(verifier, "image_constants",
                        lambda: {"QUALIFIED_IMAGES": widened, "PROFILE_ID": gh.PROFILE_ID})
    with pytest.raises(ValueError, match="differs from the catalog"):
        verifier.validate_records(verify_sources=False)


@needs_repo
def test_a_catalogued_member_the_runtime_does_not_admit_refuses(verifier, evidence):
    _edit(evidence / CATALOG.name, lambda v: _members(v).append(
        {**_members(v)[-1], "image_sha256": "f" * 64, "release_version": "9.9.9",
         "record": "agy-9.9.9-linux-x64-qualification.json"}))
    with pytest.raises(ValueError, match="differs from the catalog"):
        verifier.validate_records(verify_sources=False)


@needs_repo
@pytest.mark.parametrize("release", ["1.2.11", "1.2.12"])
def test_each_member_is_checked_against_its_own_record(verifier, evidence, release):
    name = f"agy-{release}-linux-x64-qualification.json"
    (evidence / name).unlink()
    with pytest.raises(FileNotFoundError):
        verifier.validate_records(verify_sources=False)


@needs_repo
@pytest.mark.parametrize("release", ["1.2.11", "1.2.12"])
@pytest.mark.parametrize("field,value", [
    ("image_sha256", "f" * 64), ("help_sha256", "f" * 64), ("release_version", "9.9.9"),
])
def test_a_member_record_that_disagrees_with_its_catalog_entry_refuses(verifier, evidence, release, field, value):
    _edit(evidence / f"agy-{release}-linux-x64-qualification.json", lambda v: v.__setitem__(field, value))
    with pytest.raises(ValueError, match=f"agy-{release}-linux-x64-qualification.json {field} mismatch"):
        verifier.validate_records(verify_sources=False)


@needs_repo
@pytest.mark.parametrize("release", ["1.2.11", "1.2.12"])
def test_a_member_record_with_a_failed_operation_set_refuses(verifier, evidence, release):
    _edit(evidence / f"agy-{release}-linux-x64-qualification.json",
          lambda v: v.__setitem__("records", [r for r in v["records"] if r["operation"] != "owner-loss"]))
    with pytest.raises(ValueError, match="operations mismatch"):
        verifier.validate_records(verify_sources=False)


@needs_repo
@pytest.mark.parametrize("release", ["1.2.11", "1.2.12"])
def test_each_member_record_must_pin_this_checkout(verifier, evidence, monkeypatch, release):
    name = f"agy-{release}-linux-x64-qualification.json"
    actual = json.loads((evidence / name).read_text())["source_sha256"]
    monkeypatch.setattr(verifier, "actual_source_hashes", lambda: dict(actual))
    verifier.validate_records()
    _edit(evidence / name, lambda v: v["source_sha256"].__setitem__("panel_invoker.py", "0" * 64))
    with pytest.raises(ValueError, match=f"source hashes of {name} differ"):
        verifier.validate_records()


@needs_repo
def test_a_repeated_member_refuses(verifier, evidence):
    _edit(evidence / CATALOG.name, lambda v: _members(v).append(dict(_members(v)[0])))
    with pytest.raises(ValueError, match="catalog repeats"):
        verifier.validate_records(verify_sources=False)
