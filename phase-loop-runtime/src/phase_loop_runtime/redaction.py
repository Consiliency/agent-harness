from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Iterator, Mapping

from .models import CHANGED_PATH_CATEGORIES, SourceTruthImpact


_SOURCE_TRUTH_REASON_BY_CATEGORY = {
    "docs": "docs_source_truth_touched",
    "specs": "specs_source_truth_touched",
    "active_canonical_spec": "active_specs_touched",
    "managed_root_mirror_spec": "managed_mirror_specs_touched",
    "mirror_manifest": "mirror_manifests_touched",
    "archive_manifest": "archive_manifests_touched",
    "archived_spec": "archived_specs_touched",
    "unmanaged_spec": "unmanaged_specs_touched",
    "pipeline_sources": "pipeline_sources_touched",
    "portal_contract_refs": "portal_contract_refs_touched",
    "greenfield_authority_refs": "greenfield_authority_refs_touched",
}

_CATEGORY_BY_PROTECTED_SOURCE_ROLE = {
    "active_canonical_spec": "active_canonical_spec",
    "managed_mirror_file": "managed_root_mirror_spec",
    "mirror_manifest": "mirror_manifest",
    "archive_manifest": "archive_manifest",
    "archived_spec": "archived_spec",
    "unmanaged_spec_input": "unmanaged_spec",
    "root_specs_intake": "unmanaged_spec",
}

_FORBIDDEN_METADATA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("raw_diff", re.compile(r"diff --git|@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@")),
    ("raw_spec_body", re.compile(r"raw spec bod(?:y|ies)|spec body bytes|verbatim spec", re.I)),
    ("raw_transcript", re.compile(r"raw transcript|transcript bytes|verbatim transcript", re.I)),
    ("secret_like_value", re.compile(r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}", re.I)),
    ("absolute_private_path", re.compile(r"/(?:home|users|mnt/(?:private|evidence|secure|raw|HC_Volume_[^/\s]+))/(?:[^\"'\s]+)", re.I)),
    ("provider_payload", re.compile(r"raw provider payload|provider payload|anthropic[_-]?payload|openai[_-]?payload", re.I)),
    ("credential_payload", re.compile(r"credential payload|private key|-----begin [a-z ]*private key-----", re.I)),
    ("local_env_value", re.compile(r"local env value|\.env(?:\.local)? value|process\.env\[[^\]]+\]\s*=", re.I)),
    ("private_evidence", re.compile(r"private evidence|evidence bytes|raw evidence", re.I)),
)


def classify_changed_path(path: str, protected_source_roles: Mapping[str, str] | None = None) -> str:
    normalized = _normalize_path(path)
    parts = PurePosixPath(normalized).parts
    lower = normalized.lower()
    role_category = _category_from_protected_source_role(normalized, protected_source_roles)
    if role_category is not None:
        return role_category

    if normalized.startswith("tests/") or "/tests/" in normalized or "/fixtures/" in normalized:
        return "tests"
    if lower == "readme.md" or normalized.startswith("docs/") or normalized.endswith(".md") and "/docs/" in normalized:
        return "docs"
    if _looks_like_mirror_manifest(normalized, lower):
        return "mirror_manifest"
    if _looks_like_archive_manifest(normalized, lower):
        return "archive_manifest"
    if _looks_like_active_canonical_spec(normalized, lower):
        return "active_canonical_spec"
    if _looks_like_archived_spec(normalized, lower):
        return "archived_spec"
    if normalized.startswith("specs/") or normalized.startswith("spec/"):
        return "unmanaged_spec"
    if (
        normalized.startswith(".pipeline/")
        or "pipeline.definition.json" in lower
        or normalized.startswith("packages/pipeline-schema/")
        or normalized.startswith("pipeline-sources/")
    ):
        return "pipeline_sources"
    if (
        "portal-contract" in lower
        or normalized.startswith("portal/contracts/")
        or normalized.startswith("contracts/portal/")
        or normalized.startswith("consiliency-portal/contracts/")
    ):
        return "portal_contract_refs"
    if (
        "greenfield-authority" in lower
        or normalized.startswith("greenfield/authority/")
        or normalized.startswith("greenfield/contracts/")
        or normalized.startswith("authority/greenfield/")
    ):
        return "greenfield_authority_refs"
    if _looks_like_code_path(normalized, parts):
        return "code"
    return "unknown"


def build_source_truth_impact(
    changed_paths: tuple[str, ...] | list[str] | Any,
    protected_source_roles: Mapping[str, str] | None = None,
) -> SourceTruthImpact:
    paths = _stable_paths(changed_paths)
    boundaries = tuple(
        {"path": path, "category": classify_changed_path(path, protected_source_roles)}
        for path in paths
    )
    reasons: list[str] = []
    for boundary in boundaries:
        category = boundary["category"]
        reason = _SOURCE_TRUTH_REASON_BY_CATEGORY.get(category)
        if reason is not None:
            reasons.append(reason)
        if "adoption" in boundary["path"].lower() and "contract" in boundary["path"].lower():
            reasons.append("adoption_contracts_touched")
        if "contract" in boundary["path"].lower() and category in CHANGED_PATH_CATEGORIES:
            reasons.append("contract_refs_touched")
    return SourceTruthImpact(
        changed_path_boundaries=boundaries,
        canonical_refresh_recommended=bool(reasons),
        canonical_refresh_reason_codes=tuple(sorted(dict.fromkeys(reasons))),
        redaction_posture="metadata_only",
    )


def redact_diagnostics_metadata_only(
    diagnostics: Any,
    *,
    force_all: bool = False,
) -> list[dict[str, Any]]:
    """agent-harness#243 (closeout-diagnostic redaction).

    A verification failure diagnostic's ``raw_tail`` is a bounded excerpt of
    ``verification.log`` bytes surfaced into the PERSISTED closeout record (which downstream
    prompts may read) — a real egress widening from disk log to closeout/ledger/prompt. Where
    that excerpt (or any diagnostic field, e.g. an ``argv`` token) carries a secret/PII-shaped
    value, redact that diagnostic to METADATA-ONLY: drop ``raw_tail`` and ``argv`` and keep only
    safe structural metadata (role/index/exit_code/failure_kind/truncated) plus counts and the
    matched reason. The on-disk ``verification.log`` is left FULL — only the closeout egress is
    narrowed. Detection reuses the SAME ``_FORBIDDEN_METADATA_PATTERNS`` the closeout malformed-
    metadata gate enforces, so a diagnostic that would trip that gate is instead redacted (this
    also removes a latent false ``malformed_closeout`` block when a red suite dumps a secret into
    the log). ``force_all`` (operator flag) redacts every diagnostic regardless of a match.
    """
    if not isinstance(diagnostics, (list, tuple)):
        return []
    redacted: list[dict[str, Any]] = []
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        reason = "operator_forced" if force_all else _forbidden_metadata_kind(item)
        if reason is None:
            redacted.append(dict(item))
            continue
        raw_tail = item.get("raw_tail")
        redacted.append(
            {
                "role": item.get("role"),
                "index": item.get("index"),
                "exit_code": item.get("exit_code"),
                "failure_kind": item.get("failure_kind"),
                "truncated": bool(item.get("truncated")),
                "diagnostic_status": "redacted",
                "redacted": True,
                "redaction_reason": reason,
                "raw_tail_bytes": len(raw_tail.encode("utf-8")) if isinstance(raw_tail, str) else 0,
                "argv_len": len(item["argv"]) if isinstance(item.get("argv"), (list, tuple)) else 0,
            }
        )
    return redacted


def _iter_leaf_strings(value: Any) -> Iterator[str]:
    """Depth-first yield of every leaf ``str`` value inside a nested dict/list/tuple
    structure (e.g. a diagnostic's nested ``argv`` list, or a closeout payload's nested
    ``evidence_refs``).

    agent-harness#243 CR: forbidden-metadata matching used to run against a
    ``json.dumps(...)`` serialization of the whole structure. ``json.dumps`` backslash-escapes
    an embedded double quote (``"`` -> ``\\"``), which breaks ``secret_like_value`` for a
    double-quoted secret like ``api_key="SECRETVALUE12"`` — the serialized blob becomes
    ``api_key=\\"SECRETVALUE12\\"``, the injected backslash sits between ``=`` and the quote,
    so the pattern's optional ``['\"]?`` matches zero quotes and the following
    ``[A-Za-z0-9_\\-]{12,}`` starts at the backslash and fails to match. Walking the RAW,
    unescaped leaf strings and matching each one directly closes that blind spot while
    remaining a superset of what the serialized-blob approach caught (every case that matched
    a substring of the escaped blob matches at least as well against the raw leaf it came
    from).
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_leaf_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_leaf_strings(item)


def _forbidden_metadata_kind(payload: Mapping[str, Any]) -> str | None:
    leaves = list(_iter_leaf_strings(payload))
    for kind, pattern in _FORBIDDEN_METADATA_PATTERNS:
        for leaf in leaves:
            if pattern.search(leaf):
                return kind
    return None


def metadata_redaction_diagnostic(payload: Mapping[str, Any] | None) -> dict[str, str] | None:
    if payload is None:
        return None
    kind = _forbidden_metadata_kind(payload)
    if kind is not None:
        return {"kind": "malformed_closeout", "message": f"closeout contains forbidden metadata token: {kind}"}
    return None


def _normalize_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").strip()
    return normalized[2:] if normalized.startswith("./") else normalized


def _stable_paths(paths: tuple[str, ...] | list[str] | Any) -> list[str]:
    if not isinstance(paths, (tuple, list)):
        return []
    return sorted(dict.fromkeys(_normalize_path(str(path)) for path in paths if str(path).strip()))


def _looks_like_code_path(path: str, parts: tuple[str, ...]) -> bool:
    if path.startswith(("codex-config/", "shared/skills/", "scripts/")):
        return True
    if parts and parts[0] in {"bin", "lib", "src"}:
        return True
    return PurePosixPath(path).suffix in {".py", ".sh", ".bash", ".zsh", ".toml", ".yaml", ".yml", ".json"}


def _category_from_protected_source_role(
    path: str,
    protected_source_roles: Mapping[str, str] | None,
) -> str | None:
    if not protected_source_roles:
        return None
    role = protected_source_roles.get(path) or protected_source_roles.get(path.lower())
    if role is None:
        return None
    return _CATEGORY_BY_PROTECTED_SOURCE_ROLE.get(role)


def _looks_like_mirror_manifest(path: str, lower: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name == "mirror-manifest.json" or "mirror_manifest" in lower or "/mirror-manifest" in lower


def _looks_like_archive_manifest(path: str, lower: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name == "archive-manifest.json" or "archive_manifest" in lower or "/archive-manifest" in lower


def _looks_like_active_canonical_spec(path: str, lower: str) -> bool:
    return (
        path.startswith(".pipeline/specs/active/")
        or path.startswith(".pipeline/specs/canonical/")
        or "/active-canonical/" in lower
        or "/canonical-specs/" in lower
    )


def _looks_like_archived_spec(path: str, lower: str) -> bool:
    return path.startswith(".pipeline/specs/archive/") or "/archived-specs/" in lower
