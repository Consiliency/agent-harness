"""Shared loaders for the vendored canonical outside-agent corpus.

Tests source their submissions FROM the vendored Consiliency/spec corpus
(``conformance/_contract``) rather than hand-authoring fixtures — authoring our
own shapes is exactly what concealed agent-harness#371. ``copy.deepcopy`` keeps
each caller's mutations isolated.
"""
from __future__ import annotations

import copy
import json
from importlib import resources
from pathlib import Path
from typing import Any

CONTRACT_ROOT = Path(str(resources.files("phase_loop_runtime.conformance") / "_contract"))
VECTOR_DIR = CONTRACT_ROOT / "test-vectors" / "outside-agent"


def load_vector(name: str) -> dict[str, Any]:
    """Load a canonical vector by filename stem (e.g. ``valid-work-request``)."""
    return json.loads((VECTOR_DIR / f"{name}.json").read_text(encoding="utf-8"))


def clean_submission(kind: str = "work_request") -> dict[str, Any]:
    """A canonical VALID submission of the given kind (fresh, mutable copy)."""
    stem = {
        "work_request": "valid-work-request",
        "implementation_submission": "valid-implementation-submission",
        "ambiguity_report": "valid-ambiguity-report",
    }[kind]
    return copy.deepcopy(load_vector(stem))


def source_bundle_mismatch_submission() -> dict[str, Any]:
    """A schema-VALID submission rejected only by the semantic bundle-digest check."""
    return copy.deepcopy(load_vector("invalid-source-bundle-mismatch"))


def raw_payload_submission() -> dict[str, Any]:
    """A submission carrying a forbidden raw payload field (schema-invalid)."""
    return copy.deepcopy(load_vector("invalid-raw-payload"))
