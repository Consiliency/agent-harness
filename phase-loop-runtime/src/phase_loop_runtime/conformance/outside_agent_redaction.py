"""Metadata-only guardrails for outside-agent conformance data."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .outside_agent_core import (
    OutsideAgentBlocker,
    OutsideAgentConformanceVerdict,
    OutsideAgentVerdictStatus,
)

_RAW_FIELD_NAMES = frozenset(
    {
        "raw_payload",
        "provider_response",
        "provider_response_body",
        "raw_log",
        "raw_logs",
        "copied_vector_body",
        "vector_body",
    }
)
_SECRET_FIELD_FRAGMENTS = ("api_key", "auth_token", "access_token", "secret")
_SECRET_VALUE_MARKERS = ("BEGIN PRIVATE KEY", "sk-", "xoxb-", "ghp_")
_LOCAL_ENV_FIELD_NAMES = frozenset({"env", "environment", "local_env", "local_env_value"})


def assert_outside_agent_metadata_only(value: Any) -> tuple[OutsideAgentBlocker, ...]:
    blockers: list[OutsideAgentBlocker] = []
    _walk_metadata(value, "$", blockers)
    return tuple(blockers)


def sanitize_outside_agent_verdict(
    verdict: OutsideAgentConformanceVerdict,
) -> OutsideAgentConformanceVerdict:
    blockers = verdict.blockers + assert_outside_agent_metadata_only(
        {
            "input_digest": verdict.input_digest,
            "provenance_refs": verdict.provenance_refs,
            "evidence_refs": [
                {"ref": ref.ref, "digest": ref.digest, "kind": ref.kind}
                for ref in verdict.evidence_refs
            ],
            "metadata": dict(verdict.metadata),
        }
    )
    status = (
        OutsideAgentVerdictStatus.BLOCKED
        if blockers
        else verdict.status
    )
    return replace(verdict, blockers=blockers, status=status)


def _safe_path_segment(key: str) -> str:
    """Redact a submitted key before it becomes part of a blocker ref.

    A blocker ref is a JSON pointer we echo into output. Object KEYS are
    submitter-controlled, so a secret placed in a key name would otherwise ride
    out verbatim through the pointer (agent-harness#371 round 2). Legitimate
    contract field names are short identifiers and never trip this; only a
    secret-shaped or abnormally long key is replaced with a fixed placeholder.
    """
    normalized = key.lower()
    looks_secret = (
        any(fragment in normalized for fragment in _SECRET_FIELD_FRAGMENTS)
        or any(marker.lower() in normalized for marker in _SECRET_VALUE_MARKERS)
        or len(key) > 64
    )
    return "<redacted-key>" if looks_secret else key


def _walk_metadata(value: Any, path: str, blockers: list[OutsideAgentBlocker]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{_safe_path_segment(key_text)}"
            _check_key(key_text, child_path, blockers)
            if key_text in _LOCAL_ENV_FIELD_NAMES and isinstance(child, Mapping):
                blockers.append(
                    OutsideAgentBlocker(
                        "local_env_value_present",
                        "outside-agent metadata must not contain local environment values",
                        ref=child_path,
                    )
                )
            _walk_metadata(child, child_path, blockers)
        return

    if isinstance(value, str):
        upper_value = value.upper()
        if any(marker in value for marker in _SECRET_VALUE_MARKERS):
            blockers.append(
                OutsideAgentBlocker(
                    "secret_like_value_present",
                    "outside-agent metadata contains a secret-shaped value",
                    ref=path,
                )
            )
        if "TRACEBACK" in upper_value or "\nDEBUG " in upper_value:
            blockers.append(
                OutsideAgentBlocker(
                    "raw_log_present",
                    "outside-agent metadata contains raw log content",
                    ref=path,
                )
            )
        return

    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for index, child in enumerate(value):
            _walk_metadata(child, f"{path}.{index}", blockers)


def _check_key(key: str, path: str, blockers: list[OutsideAgentBlocker]) -> None:
    normalized = key.lower()
    if normalized in _RAW_FIELD_NAMES:
        code = "raw_log_present" if "log" in normalized else "raw_payload_present"
        blockers.append(
            OutsideAgentBlocker(
                code,
                "outside-agent metadata contains raw payload content",
                ref=path,
            )
        )
    if any(fragment in normalized for fragment in _SECRET_FIELD_FRAGMENTS):
        blockers.append(
            OutsideAgentBlocker(
                "secret_like_value_present",
                "outside-agent metadata contains a secret-shaped field",
                ref=path,
            )
        )


__all__ = [
    "assert_outside_agent_metadata_only",
    "sanitize_outside_agent_verdict",
]
