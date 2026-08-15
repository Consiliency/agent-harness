"""Output-affecting producer input declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


REQUIRED_INPUTS = (
    "build_backend",
    "setuptools",
    "umask",
    "source_date_epoch",
    "archive_tool",
)
VALID_POSTURES = frozenset({"PINNED", "NORMALIZED"})


class ProducerManifestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProducerDriftFinding:
    code: str
    input_name: str


@dataclass(frozen=True)
class ProducerManifest:
    entries: Mapping[str, Mapping[str, str]]
    schema: str = "producer_manifest.v1"

    def __post_init__(self) -> None:
        if tuple(self.entries) != REQUIRED_INPUTS:
            raise ProducerManifestError(
                "producer_manifest_incomplete",
                "producer manifest must declare every output-affecting input in canonical order",
            )
        for name, entry in self.entries.items():
            if entry.get("posture") not in VALID_POSTURES:
                raise ProducerManifestError(
                    "producer_manifest_invalid_posture",
                    f"producer input {name!r} has an invalid posture",
                )


def verify_producer_manifest(
    manifest: ProducerManifest,
    actual: Mapping[str, Mapping[str, str]],
) -> ProducerDriftFinding | None:
    for name, expected in manifest.entries.items():
        observed = actual.get(name)
        if observed is None or observed.get("posture") != expected.get("posture"):
            return ProducerDriftFinding(code="producer_drift", input_name=name)
        if expected["posture"] == "PINNED" and observed.get("value") != expected.get("value"):
            return ProducerDriftFinding(code="producer_drift", input_name=name)
    return None
