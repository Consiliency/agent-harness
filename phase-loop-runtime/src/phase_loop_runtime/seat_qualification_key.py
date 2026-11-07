"""Live qualification-key and executable-projection adapters for jailed seats."""

from __future__ import annotations

from typing import Any

from . import seat_jail
from .executable_dependency import (
    AdmittedExecutableDependency,
    ExecutableDependencyError,
    admit_executable_dependency,
)
from .seat_route_contract import JailProfile, QualificationKey


def _projection_digest(projection: object | None) -> str | None:
    if projection is None:
        return None
    digest = getattr(projection, "projection_digest", None)
    if digest is None:
        digest = getattr(projection, "digest", None)
    if not isinstance(digest, str) or not digest:
        raise ValueError("projection does not expose a digest")
    return digest


def key_for_launch(
    profile: JailProfile,
    *,
    variant: str | None,
    allowlist_digest: str | None,
    projection: object | None,
) -> QualificationKey:
    """Build the exact qualification identity from this launch's live inputs."""
    host = seat_jail.host_identity()
    if not isinstance(host, str) or not host:
        raise ValueError("seat host identity is unavailable")
    return QualificationKey(
        profile_digest=seat_jail.jail_profile_digest(profile.leg),
        allowlist_digest=allowlist_digest,
        falsifier_layout=seat_jail.falsifier_layout_identity(),
        projection_digest=_projection_digest(projection),
        variant=variant,
        host_identity=host,
    )


def _requirement_parts(requirement: object) -> tuple[Any, int, str]:
    declared = getattr(requirement, "requirement", requirement)
    if declared is None:
        raise ExecutableDependencyError("authority_missing")
    authority_fd = getattr(requirement, "borrowed_authority_fd", None)
    expected_digest = getattr(requirement, "expected_authority_sha256", None)
    if authority_fd is None or expected_digest is None:
        raise ExecutableDependencyError("authority_missing")
    return declared, authority_fd, expected_digest


def admit_profile_projection(
    profile: JailProfile,
    requirement: object | None,
) -> AdmittedExecutableDependency | None:
    """Admit only the dependency shape declared by ``profile.projection``."""
    mode = profile.projection
    if mode not in {"none", "optional", "required"}:
        raise ValueError("invalid profile projection mode")

    declared = getattr(requirement, "requirement", requirement)
    if mode == "none":
        if declared is not None:
            raise ExecutableDependencyError(
                "authority_invalid",
                "profile does not permit a dependency projection",
            )
        return None
    if declared is None:
        if mode == "required":
            raise ExecutableDependencyError("authority_missing")
        return None

    if isinstance(declared, AdmittedExecutableDependency):
        if declared.provider != profile.leg:
            raise ExecutableDependencyError(
                "authority_invalid", "profile provider mismatch"
            )
        declared.revalidate()
        return declared

    dependency_requirement, authority_fd, expected_digest = _requirement_parts(
        requirement
    )
    if getattr(dependency_requirement, "provider", None) != profile.leg:
        raise ExecutableDependencyError(
            "authority_invalid", "profile provider mismatch"
        )
    return admit_executable_dependency(
        dependency_requirement,
        authority_fd,
        expected_digest,
    )


__all__ = ["admit_profile_projection", "key_for_launch"]
