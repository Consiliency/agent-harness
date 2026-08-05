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


def redact_outside_agent_serialized_payload(value: Any) -> Any:
    """Apply the final metadata-only scalar gate to a constructed payload.

    Builders choose the closed output shape; this independent final pass rejects
    raw-field names and replaces secret-shaped scalar values before bytes reach
    either CLI sink.
    """
    if isinstance(value, Mapping):
        rendered: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in _RAW_FIELD_NAMES or any(
                fragment in key_text.lower() for fragment in _SECRET_FIELD_FRAGMENTS
            ):
                raise ValueError("outside-agent serialized payload contains a raw field")
            rendered[key_text] = redact_outside_agent_serialized_payload(child)
        return rendered
    if isinstance(value, list):
        return [redact_outside_agent_serialized_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_outside_agent_serialized_payload(item) for item in value]
    if isinstance(value, str) and any(marker in value for marker in _SECRET_VALUE_MARKERS):
        return "[redacted]"
    return value


def _walk_metadata(value: Any, path: str, blockers: list[OutsideAgentBlocker]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
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
    "redact_outside_agent_serialized_payload",
    "sanitize_outside_agent_verdict",
]
