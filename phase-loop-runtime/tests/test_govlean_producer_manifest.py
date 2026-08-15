"""GOVLEAN EC-GOVLEAN-9 producer-manifest falsifiers."""
from __future__ import annotations

import importlib

import pytest

from .govlean_freeze_receipt import govlean_api_available


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.producer_manifest", "ProducerManifest"),
    reason="GOVLEAN producer-manifest capability absent",
)


REQUIRED_INPUTS = (
    "build_backend",
    "setuptools",
    "umask",
    "source_date_epoch",
    "archive_tool",
)


def _entries(*, normalized: frozenset[str] = frozenset(), **overrides: str) -> dict[str, dict[str, str]]:
    values = {
        "build_backend": "setuptools.build_meta",
        "setuptools": "79.0.1",
        "umask": "0022",
        "source_date_epoch": "1700000000",
        "archive_tool": "python-zipfile-3.10",
    }
    values.update(overrides)
    return {
        name: {
            "value": value,
            "posture": "NORMALIZED" if name in normalized else "PINNED",
        }
        for name, value in values.items()
    }


def _manifest(module, **overrides):
    return module.ProducerManifest(entries=_entries(**overrides))


def test_complete_manifest_records_every_output_affecting_input_with_the_v1_schema():
    producer = importlib.import_module("phase_loop_runtime.producer_manifest")

    manifest = _manifest(producer)

    assert manifest.schema == "producer_manifest.v1"
    assert tuple(manifest.entries) == REQUIRED_INPUTS
    assert producer.verify_producer_manifest(manifest, _entries()) is None


@pytest.mark.parametrize(
    ("input_name", "changed_value"),
    (
        ("build_backend", "custom.backend"),
        ("setuptools", "80.0.0"),
        ("umask", "0002"),
        ("source_date_epoch", "1700000001"),
        ("archive_tool", "bsd-tar-3.6"),
    ),
)
def test_every_pinned_input_class_reports_producer_drift_before_a_content_comparison(input_name, changed_value):
    producer = importlib.import_module("phase_loop_runtime.producer_manifest")
    manifest = _manifest(producer)

    finding = producer.verify_producer_manifest(manifest, _entries(**{input_name: changed_value}))

    assert finding.code == "producer_drift"
    assert finding.input_name == input_name


def test_normalized_input_difference_does_not_claim_producer_drift():
    producer = importlib.import_module("phase_loop_runtime.producer_manifest")
    manifest = producer.ProducerManifest(
        entries=_entries(normalized=frozenset({"source_date_epoch"}))
    )

    finding = producer.verify_producer_manifest(
        manifest,
        _entries(normalized=frozenset({"source_date_epoch"}), source_date_epoch="1700000001"),
    )

    assert finding is None


def test_manifest_rejects_missing_or_unclassified_output_inputs():
    producer = importlib.import_module("phase_loop_runtime.producer_manifest")
    missing_archive_tool = _entries()
    del missing_archive_tool["archive_tool"]

    with pytest.raises(producer.ProducerManifestError) as excinfo:
        producer.ProducerManifest(entries=missing_archive_tool)

    assert excinfo.value.code == "producer_manifest_incomplete"
