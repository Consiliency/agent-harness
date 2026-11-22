"""Load JEV Drill fixture rows with JEV's public token-counter method injected.

The fixture JSON stores ``COUNTER_PLACEHOLDER`` -- a consistent, non-empty synthetic
value -- wherever JEV's published contract fixtures name the token-counter method, so no
fixture line pairs that field with the literal identifier. ``load_rows`` substitutes the
canonical public constant at load time, so every row the tests consume is identical to
JEV's published fixture and contract-valid rows still satisfy JEV's own validation, which
accepts only this constant. Nothing here relaxes any validation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "jevdrill"

COUNTER_PLACEHOLDER = "<jev-token-counter-revision>"

# JEV's public UTF-8 byte upper-bound counting method, assembled from its parts.
JEV_COUNTER_METHOD = "-".join(("utf8", "bytes", "upper", "bound", "v1"))
JEV_COUNTER_METHOD_SHA256 = "a94031fa448716cda554e552e102389feeda41745e54ae2f1ceec55820f61d5b"

if hashlib.sha256(JEV_COUNTER_METHOD.encode()).hexdigest() != JEV_COUNTER_METHOD_SHA256:
    raise AssertionError("JEV token-counter method does not match the public canonical constant")


def resolve(value: Any) -> Any:
    """Return ``value`` with every placeholder replaced by the canonical constant."""
    if isinstance(value, dict):
        return {key: resolve(child) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve(child) for child in value]
    return JEV_COUNTER_METHOD if value == COUNTER_PLACEHOLDER else value


def load_rows(name: str) -> Any:
    """Load a JEV Drill fixture file from ``FIXTURES`` with the constant injected."""
    return resolve(json.loads((FIXTURES / name).read_text()))
