"""RRIMAGE SL-0: the ``review_runner_pin.v1`` record and rules P1–P10 (contract §2, §4).

Each test enters through ``validate_pin_record(record, repo_root)`` on a synthetic checkout
that holds the checked-in Containerfile and ``PIN.json`` and a synthetic manifest and config
whose digests are computed here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

import pytest

from phase_loop_runtime import review_runner_pin as rp
from phase_loop_runtime.review_runner_pin import (
    PinRecordError,
    apply_receipt,
    assemble_built_record,
    load_pin_record,
    record_sha256,
    validate_pin_record,
)

PKG_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PKG_ROOT.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_runner_pin"
CONTAINERFILE = "phase-loop-runtime/images/review-runner/Containerfile"
PIN_JSON = "phase-loop-runtime/tests/data/landlock-exec/PIN.json"
ARTIFACT_SCHEMA = REPO_ROOT / "plans/artifacts/rrimage-v1-pin-record.schema.json"
EVIDENCE = "plans/evidence/review-runner"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / CONTAINERFILE).is_file() or not (REPO_ROOT / PIN_JSON).is_file(),
    reason="needs the repository checkout (Containerfile and PIN.json)")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def dump(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


class Checkout:
    """A synthetic repo root with the real Containerfile and PIN.json and synthetic bytes."""

    def __init__(self, root: Path):
        self.root = root
        for rel in (CONTAINERFILE, PIN_JSON):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, root / rel)
        (root / EVIDENCE).mkdir(parents=True, exist_ok=True)
        self.pin = json.loads((root / PIN_JSON).read_text())
        self.containerfile_sha256 = sha((root / CONTAINERFILE).read_bytes())

    def write(self, rel: str, data: bytes) -> None:
        (self.root / rel).write_bytes(data)

    def commit(self, record, manifest: bytes, config: bytes) -> None:
        self.write(record["artifact"]["manifest_path"], manifest)
        self.write(record["artifact"]["config_path"], config)

    def built(self, *, manifest=None, config=None):
        """A valid built record, after committing its manifest and config bytes."""
        record = fixture("built-record.json")
        record["source"]["containerfile_sha256"] = self.containerfile_sha256
        record["helper"]["sha256"] = self.pin["helper_sha256"]
        record["helper"]["source_commit"] = self.pin["commit"]
        config_doc = fixture("config.json") if config is None else config
        labels = config_doc["config"]["Labels"]
        labels.setdefault(rp.REVISION_LABEL, None)
        if labels[rp.REVISION_LABEL] == "computed-in-test":
            labels[rp.REVISION_LABEL] = record["source"]["commit"]
        if labels.get(rp.CONTAINERFILE_LABEL) == "computed-in-test":
            labels[rp.CONTAINERFILE_LABEL] = self.containerfile_sha256
        config_bytes = dump(config_doc)
        manifest_doc = fixture("manifest.json") if manifest is None else manifest
        manifest_doc["config"]["digest"] = "sha256:" + sha(config_bytes)
        manifest_doc["config"]["size"] = len(config_bytes)
        manifest_bytes = dump(manifest_doc)
        digest = "sha256:" + sha(manifest_bytes)
        record["artifact"]["manifest_digest"] = digest
        record["artifact"]["manifest_size"] = len(manifest_bytes)
        record["platform"]["config_digest"] = "sha256:" + sha(config_bytes)
        record["build"]["first_manifest_digest"] = digest
        record["build"]["reproduced"]["second_manifest_digest"] = digest
        self.commit(record, manifest_bytes, config_bytes)
        self.manifest_bytes, self.config_bytes = manifest_bytes, config_bytes
        return record

    def receipt(self, record):
        receipt = fixture("receipt.json")
        digest = record["artifact"]["manifest_digest"]
        receipt.update({
            "input_archive_sha256": record["artifact"]["oci_archive_sha256"],
            "registry_manifest_digest": digest,
            "docker_content_digest": digest,
            "raw_manifest_sha256": digest.split(":", 1)[1],
            "config_digest": record["platform"]["config_digest"],
            "helper_sha256": record["helper"]["sha256"],
        })
        return receipt

    def pinned(self):
        built = self.built()
        return apply_receipt(built, self.receipt(built), image=fixture("image.json"),
                             recorded_at="2026-11-23T12:00:00Z")

    def validate(self, record, **kwargs):
        return validate_pin_record(record, self.root, **kwargs)


@pytest.fixture
def checkout(tmp_path):
    return Checkout(tmp_path)


def strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)
    elif isinstance(value, str):
        yield value


def refuse(checkout, record, code, rule=None, **kwargs):
    """Assert the production call refuses with ``code``, and that its message holds no value."""
    with pytest.raises(PinRecordError) as caught:
        checkout.validate(record, **kwargs)
    error = caught.value
    assert error.code == code, (error.code, error.rule, error.field)
    if rule is not None:
        assert error.rule == rule
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    message = str(error)
    for value in strings(record):
        if len(value) >= 12:
            assert value not in message
    for value in re.findall(r"[0-9a-f]{40,}", json.dumps(record)):
        assert value not in message
    return error


def set_path(record, dotted, value):
    record = copy.deepcopy(record)
    *parents, last = dotted.split(".")
    node = record
    for part in parents:
        node = node[part]
    node[last] = value
    return record


# -- packaging and valid records ----------------------------------------------------------------

@pytest.mark.skipif(not ARTIFACT_SCHEMA.is_file(), reason="needs the planning artifact")
def test_packaged_schema_equals_the_frozen_artifact():
    packaged = PKG_ROOT / "src/phase_loop_runtime" / rp.SCHEMA_RESOURCE
    assert packaged.read_bytes() == ARTIFACT_SCHEMA.read_bytes()
    assert rp.schema_bytes() == ARTIFACT_SCHEMA.read_bytes()


def test_pyproject_ships_the_schema_as_package_data():
    assert '"contracts/placement/**"' in (PKG_ROOT / "pyproject.toml").read_text()


def test_valid_built_record(checkout):
    record = checkout.built()
    verdict = checkout.validate(record)
    assert (verdict.status, verdict.record_status, verdict.pinned) == ("built", "built", False)
    assert verdict.record_sha256 == record_sha256(record)
    with pytest.raises(PinRecordError) as caught:
        verdict.require_pinned()
    assert caught.value.code == "pin_not_pinned"


def test_valid_pinned_record(checkout):
    record = checkout.pinned()
    verdict = checkout.validate(record)
    assert (verdict.status, verdict.pinned) == ("pinned", True)
    verdict.require_pinned()
    image = fixture("image.json")
    assert record["image"]["reference"] == (
        f"{image['registry']}/{image['repository']}@{record['artifact']['manifest_digest']}")


def test_valid_built_record_without_a_second_build(checkout):
    record = checkout.built()
    record["build"]["reproduced"] = {"attempted": False, "second_manifest_digest": None,
                                     "equal": None, "differing_layers": [],
                                     "deferred_finding": None}
    assert checkout.validate(record).status == "built"


def test_valid_built_record_with_a_reproducibility_mismatch(checkout):
    record = checkout.built()
    record["build"]["reproduced"].update({
        "second_manifest_digest": "sha256:" + "6" * 64, "equal": False,
        "differing_layers": ["sha256:" + "7" * 64],
        "deferred_finding": "Consiliency/agent-harness#1"})
    assert checkout.validate(record).status == "built"


def test_load_pin_record_round_trip_and_strict_json(tmp_path, checkout):
    record = checkout.built()
    path = tmp_path / "pin-record.json"
    path.write_bytes(dump(record))
    assert load_pin_record(path) == record
    for raw in (b'{"a": 1, "a": 2}', b'{"a": NaN}', b"[]", b"not json", b"\xff"):
        path.write_bytes(raw)
        with pytest.raises(PinRecordError) as caught:
            load_pin_record(path)
        assert caught.value.code == "pin_schema_invalid"
    with pytest.raises(PinRecordError):
        load_pin_record(tmp_path / "missing.json")


# -- P1 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda r: r.update(extra=1),
    lambda r: r["artifact"].update(extra=1),
    lambda r: r["build"]["reproduced"].update(extra=1),
    lambda r: r.pop("recorded_at"),
    lambda r: r["artifact"].update(manifest_size=True),
    lambda r: r["artifact"].update(manifest_size=1.0),
    lambda r: r.update(status="pinned"),
    lambda r: r.update(recorded_at="2026-13-40T99:00:00Z"),
], ids=["top-extra", "nested-extra", "deep-extra", "missing", "bool-int", "float-int",
        "pinned-without-receipt", "bad-time"])
def test_p1_schema_refuses(checkout, mutate):
    record = checkout.built()
    mutate(record)
    refuse(checkout, record, "pin_schema_invalid", "P1")


def test_p1_refuses_a_receipt_on_a_built_record(checkout):
    pinned = checkout.pinned()
    pinned["status"] = "built"
    refuse(checkout, pinned, "pin_schema_invalid", "P1")


# -- P2 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("reference", [
    "registry.example.test:5000/openshell/review-runner@sha256:" + "8" * 64,
    "registry.example.test:5000/openshell/review-runner:latest@{digest}",
    "registry.example.test:5000/openshell/other@{digest}",
])
def test_p2_reference_mismatch(checkout, reference):
    record = checkout.pinned()
    record["image"]["reference"] = reference.format(digest=record["artifact"]["manifest_digest"])
    refuse(checkout, record, "pin_reference_mismatch", "P2")


# -- P3 -----------------------------------------------------------------------------------------

def test_p3_artifact_index_media_type_refused(checkout):
    record = set_path(checkout.built(), "artifact.manifest_media_type", OCI_INDEX)
    refuse(checkout, record, "pin_index_refused", "P3")


def test_p3_receipt_index_media_type_refused(checkout):
    record = set_path(checkout.pinned(), "receipt.raw_manifest_media_type", OCI_INDEX)
    refuse(checkout, record, "pin_index_refused", "P3")


def test_p3_committed_index_manifest_refused(checkout):
    manifest = fixture("manifest.json")
    manifest["mediaType"] = OCI_INDEX
    record = checkout.built(manifest=manifest)
    refuse(checkout, record, "pin_index_refused")


# -- P4 and the stale marker --------------------------------------------------------------------

def make_stale(checkout):
    path = checkout.root / CONTAINERFILE
    path.write_bytes(path.read_bytes() + b"# later edit\n")


def write_marker(checkout, record_hash, **extra):
    marker = {"schema": "review_runner_pin_stale.v1", "record_sha256": record_hash,
              "reason": "Containerfile changed after the pin", **extra}
    checkout.write(rp.STALE_MARKER_PATH, dump(marker))


@pytest.mark.parametrize("kind", ["built", "pinned"])
def test_p4_strict_by_default(checkout, kind):
    record = checkout.built() if kind == "built" else checkout.pinned()
    make_stale(checkout)
    refuse(checkout, record, "pin_containerfile_stale", "P4")
    write_marker(checkout, record_sha256(record))
    refuse(checkout, record, "pin_containerfile_stale", "P4")


def test_p4_stale_marker_accepted_only_when_allowed_and_named(checkout):
    record = checkout.pinned()
    make_stale(checkout)
    refuse(checkout, record, "pin_containerfile_stale", "P4", allow_stale_marker=True)
    write_marker(checkout, "9" * 64)
    refuse(checkout, record, "pin_containerfile_stale", "P4", allow_stale_marker=True)
    write_marker(checkout, record_sha256(record), extra="x")
    refuse(checkout, record, "pin_containerfile_stale", "P4", allow_stale_marker=True)
    write_marker(checkout, record_sha256(record))
    verdict = checkout.validate(record, allow_stale_marker=True)
    assert (verdict.status, verdict.record_status, verdict.pinned) == ("stale", "pinned", False)
    with pytest.raises(PinRecordError) as caught:
        verdict.require_pinned()
    assert caught.value.code == "pin_not_pinned"
    other = set_path(record, "recorded_at", "2026-11-24T00:00:00Z")
    refuse(checkout, other, "pin_containerfile_stale", "P4", allow_stale_marker=True)


def test_p4_stale_marker_does_not_waive_other_rules(checkout):
    record = checkout.pinned()
    make_stale(checkout)
    bad = set_path(record, "receipt.helper_sha256", "a" * 64)
    write_marker(checkout, record_sha256(bad))
    refuse(checkout, bad, "pin_receipt_mismatch", "P6", allow_stale_marker=True)


def test_p4_marker_ignored_when_containerfile_current(checkout):
    record = checkout.pinned()
    write_marker(checkout, record_sha256(record))
    assert checkout.validate(record, allow_stale_marker=True).status == "pinned"


def test_p4_edited_containerfile_hash_fails_source_binding(checkout):
    record = checkout.built()
    make_stale(checkout)
    record["source"]["containerfile_sha256"] = sha((checkout.root / CONTAINERFILE).read_bytes())
    refuse(checkout, record, "pin_source_mismatch", "P9")


# -- P5 -----------------------------------------------------------------------------------------

def test_p5_helper_sha_mismatch(checkout):
    record = set_path(checkout.built(), "helper.sha256", "b" * 64)
    refuse(checkout, record, "pin_helper_mismatch", "P5")


def test_p5_helper_commit_mismatch(checkout):
    record = set_path(checkout.built(), "helper.source_commit", "c" * 40)
    refuse(checkout, record, "pin_helper_mismatch", "P5")


def test_p5_pin_json_helper_sha_mismatch(checkout):
    record = checkout.built()
    pin = dict(checkout.pin, helper_sha256="d" * 64)
    checkout.write(PIN_JSON, dump(pin))
    refuse(checkout, record, "pin_helper_mismatch", "P5")


def test_p5_containerfile_hash_line_mismatch(checkout):
    record = checkout.built()
    path = checkout.root / CONTAINERFILE
    path.write_text(path.read_text().replace(checkout.pin["helper_sha256"], "e" * 64))
    refuse(checkout, record, "pin_helper_mismatch", "P5")


def test_p5_helper_destination_mismatch(checkout):
    record = checkout.built()
    path = checkout.root / CONTAINERFILE
    text = path.read_text()
    assert "/landlock-exec /usr/libexec/agent-toolkit/landlock-exec" in text
    path.write_text(text.replace("/landlock-exec /usr/libexec/agent-toolkit/landlock-exec",
                                 "/landlock-exec /usr/local/bin/landlock-exec"))
    refuse(checkout, record, "pin_helper_mismatch", "P5")


# -- P6 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("registry_manifest_digest", "sha256:" + "f" * 64),
    ("docker_content_digest", "sha256:" + "f" * 64),
    ("raw_manifest_sha256", "f" * 64),
    ("raw_manifest_media_type", DOCKER_MANIFEST),
    ("config_digest", "sha256:" + "f" * 64),
    ("helper_sha256", "f" * 64),
    ("input_archive_sha256", "f" * 64),
])
def test_p6_receipt_mismatch(checkout, field, value):
    record = set_path(checkout.pinned(), f"receipt.{field}", value)
    refuse(checkout, record, "pin_receipt_mismatch", "P6")


@pytest.mark.parametrize("field,value", [
    ("container_state", "running"), ("started_at_zero", False), ("entrypoint_started", True)])
def test_p6_start_evidence_refused(checkout, field, value):
    record = set_path(checkout.pinned(), f"receipt.{field}", value)
    with pytest.raises(PinRecordError) as caught:
        checkout.validate(record)
    assert caught.value.code in {"pin_schema_invalid", "pin_receipt_mismatch"}


# -- P7 -----------------------------------------------------------------------------------------

BASE64_40 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNk"


@pytest.mark.parametrize("field,value", [
    ("receipt.ref", "https://github.com/ViperJuice/ai-stack/ghp_abc"),
    ("receipt.ref", "https://github.com/ViperJuice/ai-stack/issues/1?token=x"),
    ("receipt.ref", "https://github.com/ViperJuice/ai-stack/x?u=https://user:pw@example.test"),
    ("receipt.ref", "https://github.com/ViperJuice/ai-stack/" + BASE64_40),
    ("build.buildkit_image", "docker.io/moby/secret@sha256:" + "2" * 64),
    ("build.buildkit_image", BASE64_40 + "@sha256:" + "2" * 64),
])
def test_p7_credential_sentinel_refused(checkout, field, value):
    record = set_path(checkout.pinned(), field, value)
    refuse(checkout, record, "pin_credential_sentinel", "P7")


def test_p7_digest_fields_are_exempt_from_the_base64_test(checkout):
    record = checkout.pinned()
    assert re.search(r"[A-Za-z0-9+/]{40,}", record["source"]["commit"])
    assert re.search(r"[A-Za-z0-9+/]{40,}", record["build"]["buildkit_image"])
    assert checkout.validate(record).status == "pinned"
    exempt = rp._digest_fields()
    for path in [("source", "commit"), ("helper", "source_commit"), ("artifact", "manifest_digest"),
                 ("receipt", "ref_sha256"), ("build", "reproduced", "differing_layers", "*")]:
        assert exempt[path] == "full"
    assert exempt[("build", "buildkit_image")] == exempt[("image", "reference")] == "suffix"
    assert ("receipt", "ref") not in exempt and ("receipt", "pull_account") not in exempt


# -- P8 -----------------------------------------------------------------------------------------

def test_p8_recorded_before_pull_refused(checkout):
    record = set_path(checkout.pinned(), "recorded_at", "2026-11-23T09:59:59Z")
    refuse(checkout, record, "pin_receipt_mismatch", "P8")


# -- P9 -----------------------------------------------------------------------------------------

def test_p9_first_manifest_digest_mismatch(checkout):
    record = checkout.built()
    record["build"]["first_manifest_digest"] = "sha256:" + "a" * 64
    record["build"]["reproduced"]["second_manifest_digest"] = "sha256:" + "a" * 64
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_manifest_bytes_mismatch(checkout):
    record = checkout.built()
    checkout.write(record["artifact"]["manifest_path"], checkout.manifest_bytes + b" ")
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_manifest_size_mismatch(checkout):
    record = checkout.built()
    record["artifact"]["manifest_size"] += 1
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_manifest_config_descriptor_mismatch(checkout):
    record = checkout.built()
    record["platform"]["config_digest"] = "sha256:" + sha(b"other")
    checkout.write(record["artifact"]["config_path"], b"other")
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_config_bytes_mismatch(checkout):
    record = checkout.built()
    checkout.write(record["artifact"]["config_path"], checkout.config_bytes + b" ")
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_missing_committed_manifest(checkout):
    record = checkout.built()
    (checkout.root / record["artifact"]["manifest_path"]).unlink()
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_config_platform_mismatch(checkout):
    config = fixture("config.json")
    config["architecture"] = "arm64"
    record = checkout.built(config=config)
    refuse(checkout, record, "pin_digest_mismatch", "P9")


def test_p9_manifest_media_type_differs_from_record(checkout):
    manifest = fixture("manifest.json")
    manifest["mediaType"] = DOCKER_MANIFEST
    record = checkout.built(manifest=manifest)
    refuse(checkout, record, "pin_digest_mismatch", "P9")


@pytest.mark.parametrize("label", [rp.REVISION_LABEL, rp.CONTAINERFILE_LABEL])
def test_p9_source_label_mismatch(checkout, label):
    config = fixture("config.json")
    config["config"]["Labels"][label] = "0" * 64
    record = checkout.built(config=config)
    refuse(checkout, record, "pin_source_mismatch", "P9")


def test_p9_source_labels_missing(checkout):
    config = fixture("config.json")
    config["config"]["Labels"] = {}
    record = checkout.built(config=config)
    refuse(checkout, record, "pin_source_mismatch", "P9")


# -- P10 ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("change", [
    {"attempted": False},
    {"equal": False},
    {"second_manifest_digest": "sha256:" + "6" * 64},
    {"second_manifest_digest": "sha256:" + "6" * 64, "equal": False},
    {"second_manifest_digest": "sha256:" + "6" * 64, "equal": False,
     "differing_layers": ["sha256:" + "7" * 64]},
    {"differing_layers": ["sha256:" + "7" * 64]},
    {"second_manifest_digest": None},
], ids=["unattempted-with-second", "equal-false-same", "equal-true-differs",
        "no-layers", "no-finding", "layers-when-equal", "attempted-no-second"])
def test_p10_reproducibility_inconsistent(checkout, change):
    record = checkout.built()
    record["build"]["reproduced"].update(change)
    refuse(checkout, record, "pin_reproducibility_inconsistent", "P10")


# -- assemble_built_record ----------------------------------------------------------------------

def make_layout(checkout, root: Path, *, descriptors=None):
    """An OCI layout holding the checkout's synthetic manifest and config blobs."""
    record = checkout.built()
    blobs = root / "blobs" / "sha256"
    blobs.mkdir(parents=True, exist_ok=True)
    for data in (checkout.manifest_bytes, checkout.config_bytes):
        (blobs / sha(data)).write_bytes(data)
    descriptor = {"mediaType": record["artifact"]["manifest_media_type"],
                  "digest": record["artifact"]["manifest_digest"],
                  "size": record["artifact"]["manifest_size"]}
    (root / "oci-layout").write_text('{"imageLayoutVersion": "1.0.0"}')
    index = {"schemaVersion": 2, "mediaType": OCI_INDEX,
             "manifests": [descriptor] if descriptors is None else descriptors(descriptor, blobs)}
    (root / "index.json").write_bytes(dump(index))
    meta = {"oci_archive_sha256": record["artifact"]["oci_archive_sha256"],
            "source": {"commit": record["source"]["commit"],
                       "containerfile_sha256": record["source"]["containerfile_sha256"]},
            "helper": {"sha256": record["helper"]["sha256"],
                       "source_commit": record["helper"]["source_commit"]},
            "build": {key: value for key, value in record["build"].items()
                      if key not in {"tool", "first_manifest_digest"}},
            "recorded_at": record["recorded_at"]}
    return record, meta


def test_assemble_built_record_from_layout(checkout, tmp_path):
    expected, meta = make_layout(checkout, tmp_path / "layout")
    assembled = assemble_built_record(tmp_path / "layout", meta)
    assert assembled.record == expected
    assert assembled.manifest_bytes == checkout.manifest_bytes
    assert assembled.config_bytes == checkout.config_bytes
    checkout.commit(assembled.record, assembled.manifest_bytes, assembled.config_bytes)
    assert checkout.validate(assembled.record).status == "built"


def nested_index(descriptor, blobs):
    nested = dump({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [descriptor]})
    (blobs / sha(nested)).write_bytes(nested)
    return [{"mediaType": OCI_INDEX, "digest": "sha256:" + sha(nested), "size": len(nested)}]


@pytest.mark.parametrize("descriptors,code", [
    (nested_index, "pin_index_refused"),
    (lambda d, _b: [d, dict(d)], "pin_digest_mismatch"),
    (lambda d, _b: [], "pin_digest_mismatch"),
    (lambda d, _b: [dict(d, size=d["size"] + 1)], "pin_digest_mismatch"),
    (lambda d, _b: [dict(d, digest="sha256:" + "a" * 64)], "pin_digest_mismatch"),
    (lambda d, _b: [dict(d, digest="sha256:../../x")], "pin_digest_mismatch"),
], ids=["nested-index", "second-descriptor", "no-descriptor", "size", "digest", "traversal"])
def test_assemble_refuses_bad_layouts(checkout, tmp_path, descriptors, code):
    _record, meta = make_layout(checkout, tmp_path / "layout", descriptors=descriptors)
    with pytest.raises(PinRecordError) as caught:
        assemble_built_record(tmp_path / "layout", meta)
    assert caught.value.code == code


def test_assemble_refuses_a_tampered_blob(checkout, tmp_path):
    _record, meta = make_layout(checkout, tmp_path / "layout")
    (tmp_path / "layout/blobs/sha256" / sha(checkout.config_bytes)).write_bytes(b"tampered")
    with pytest.raises(PinRecordError) as caught:
        assemble_built_record(tmp_path / "layout", meta)
    assert caught.value.code == "pin_digest_mismatch"


def test_assemble_refuses_a_source_label_mismatch(checkout, tmp_path):
    _record, meta = make_layout(checkout, tmp_path / "layout")
    meta["source"]["commit"] = "f" * 40
    with pytest.raises(PinRecordError) as caught:
        assemble_built_record(tmp_path / "layout", meta)
    assert caught.value.code == "pin_source_mismatch"


# -- apply_receipt ------------------------------------------------------------------------------

def test_apply_receipt_does_not_mutate_its_input(checkout):
    built = checkout.built()
    before = copy.deepcopy(built)
    pinned = apply_receipt(built, checkout.receipt(built), image=fixture("image.json"),
                           recorded_at="2026-11-23T12:00:00Z")
    assert built == before and pinned["status"] == "pinned"


def test_apply_receipt_refuses_a_mismatched_receipt(checkout):
    built = checkout.built()
    receipt = dict(checkout.receipt(built), docker_content_digest="sha256:" + "f" * 64)
    with pytest.raises(PinRecordError) as caught:
        apply_receipt(built, receipt, image=fixture("image.json"),
                      recorded_at="2026-11-23T12:00:00Z")
    assert caught.value.code == "pin_receipt_mismatch"


def test_apply_receipt_refuses_an_already_pinned_record(checkout):
    pinned = checkout.pinned()
    with pytest.raises(PinRecordError) as caught:
        apply_receipt(pinned, pinned["receipt"], image=fixture("image.json"))
    assert caught.value.code == "pin_schema_invalid"


def test_record_sha256_is_canonical(checkout):
    record = checkout.built()
    reordered = json.loads(json.dumps(record, sort_keys=True))
    assert record_sha256(record) == record_sha256(reordered)
    assert record_sha256(record) != record_sha256(set_path(record, "recorded_at",
                                                           "2026-11-22T10:00:01Z"))
