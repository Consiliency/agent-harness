"""GOVLEAN EC-GOVLEAN-4 local proof-stage falsifiers."""
from __future__ import annotations

import importlib


def _entries(*, setuptools: str = "79.0.1") -> dict[str, dict[str, str]]:
    return {
        "build_backend": {"value": "setuptools.build_meta", "posture": "PINNED"},
        "setuptools": {"value": setuptools, "posture": "PINNED"},
        "umask": {"value": "0022", "posture": "PINNED"},
        "source_date_epoch": {"value": "1700000000", "posture": "PINNED"},
        "archive_tool": {"value": "python-zipfile-3.10", "posture": "PINNED"},
    }


def test_local_stage_cache_uses_sorted_content_digests_and_never_reuses_stale_input_or_producer_state(tmp_path):
    stages = importlib.import_module("phase_loop_runtime.proof_stages")
    producer = importlib.import_module("phase_loop_runtime.producer_manifest")
    cache = stages.LocalStageCache(tmp_path / "cache")
    baseline = producer.ProducerManifest(entries=_entries())
    calls: list[str] = []

    def runner():
        calls.append("run")
        return {"run": len(calls)}

    first = cache.get_or_run("proof-stage", ("digest-b", "digest-a"), baseline, runner)
    same_inputs_different_order = cache.get_or_run(
        "proof-stage", ("digest-a", "digest-b"), baseline, runner
    )
    changed_input = cache.get_or_run("proof-stage", ("digest-a", "digest-c"), baseline, runner)
    changed_producer = cache.get_or_run(
        "proof-stage",
        ("digest-a", "digest-c"),
        producer.ProducerManifest(entries=_entries(setuptools="80.0.0")),
        runner,
    )

    assert first == same_inputs_different_order
    assert changed_input != first
    assert changed_producer != changed_input
    assert calls == ["run", "run", "run"]


def test_independent_local_stages_return_every_success_and_failure_without_short_circuiting():
    stages = importlib.import_module("phase_loop_runtime.proof_stages")

    def broken_stage():
        raise RuntimeError("deliberate independent failure")

    outcomes = stages.run_independent_stages(
        {
            "first": lambda: "first-result",
            "broken": broken_stage,
            "last": lambda: "last-result",
        },
        max_workers=3,
    )

    assert set(outcomes) == {"first", "broken", "last"}
    assert outcomes["first"].ok is True
    assert outcomes["first"].value == "first-result"
    assert outcomes["last"].ok is True
    assert outcomes["last"].value == "last-result"
    assert outcomes["broken"].ok is False
    assert isinstance(outcomes["broken"].error, RuntimeError)
    assert "deliberate independent failure" in str(outcomes["broken"].error)
