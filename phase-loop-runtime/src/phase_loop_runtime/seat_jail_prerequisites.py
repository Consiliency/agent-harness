"""Host prerequisites shared by seat qualification and ``phase-loop doctor``."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Mapping


_QUALIFY = "then run `phase-loop seat-sandbox qualify`"
_UNLOCKS = "seat-jail qualification (jailed review seats)"

CHECKLIST_BY_NAME: dict[str, str] = {
    "pytest": "LA1-RELEASE",
    "bwrap": "LA1-PACKAGES",
    "setpriv": "LA1-PACKAGES",
    "nsenter": "LA1-PACKAGES",
    "egress_isolation": "LA1-PACKAGES",
    "legacy_tiocsti": "LA1-TIOCSTI",
    "subordinate_ids": "LA1-SUBID",
    "machine_id": "LA1-MACHINE-ID",
}

_INSTALL_FIXES = {
    "managed": (
        "Ask the host administrator to install a managed release that carries the seat "
        "dependencies (`docs/team-host-admin.md`, item LA1-RELEASE), {qualify}."
    ),
    "uv_tool": "Run `uv tool upgrade phase-loop-runtime`, {qualify}.",
    "pip": (
        "Run `pip install --upgrade phase-loop-runtime` in the runtime's environment, "
        "{qualify}."
    ),
    "source": "Run `uv sync --project phase-loop-runtime` in the checkout, {qualify}.",
    "unknown": (
        "Reinstall `phase-loop-runtime` with the installer that installed it, {qualify}."
    ),
}


def fix_sentence(name: str, *, deployment: str) -> str:
    """Return the single operator sentence for a missing prerequisite."""

    if name not in CHECKLIST_BY_NAME:
        raise ValueError(f"unknown seat prerequisite: {name}")
    if name == "pytest":
        template = _INSTALL_FIXES.get(deployment, _INSTALL_FIXES["unknown"])
        return template.format(qualify=_QUALIFY)
    checklist = CHECKLIST_BY_NAME[name]
    return (
        "Ask the host administrator to complete `docs/team-host-admin.md`, item "
        f"{checklist}, {_QUALIFY}."
    )


# Compatibility for callers that render one fixed sentence outside doctor.  The qualification
# path below selects the sentence for the running deployment kind.
PYTEST_FIX = fix_sentence("pytest", deployment="uv_tool")


def pytest_status() -> str:
    """``present``, ``missing`` or ``unknown`` when inventory cannot run."""

    from . import review_stage

    try:
        return "present" if review_stage.falsifier_distribution_available("pytest") else "missing"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"


def _predicates() -> dict[str, Callable[[], bool | str]]:
    from . import sandbox_egress, seat_host_namespace, seat_jail, seat_uid

    return {
        "pytest": pytest_status,
        "bwrap": lambda: os.access("/usr/bin/bwrap", os.X_OK),
        "setpriv": lambda: os.access("/usr/bin/setpriv", os.X_OK),
        "nsenter": lambda: os.access("/usr/bin/nsenter", os.X_OK),
        "egress_isolation": sandbox_egress.egress_isolation_available,
        "legacy_tiocsti": seat_jail.tiocsti_safe,
        "subordinate_ids": lambda: (
            seat_uid.subordinate_range(seat_uid.SUBUID_FILE) is not None
            and seat_uid.subordinate_range(seat_uid.SUBGID_FILE) is not None
            and seat_host_namespace.subordinate_ranges_disjoint()
        ),
        "machine_id": lambda: seat_jail.host_identity() is not None,
    }


def missing() -> list[str]:
    """Names known to be missing without raising."""

    return [row["name"] for row in check() if row["status"] == "missing"]


def check(
    *,
    deployment: str | None = None,
    predicates: Mapping[str, Callable[[], bool | str]] | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    """Return the closed prerequisite rows used by doctor and qualification advice."""

    from . import seat_subject

    deployment = deployment or seat_subject.deployment_kind()
    platform = sys.platform if platform is None else platform
    probes = dict(predicates or _predicates())
    rows: list[dict[str, Any]] = []
    for name, checklist in CHECKLIST_BY_NAME.items():
        row: dict[str, Any] = {
            "name": name,
            "status": "unknown",
            "unlocks": _UNLOCKS,
            "checklist": checklist,
        }
        if not platform.startswith("linux"):
            row["reason"] = "platform_unsupported"
            rows.append(row)
            continue
        try:
            observed = probes[name]()
            if observed in {"present", "missing", "unknown"}:
                row["status"] = observed
            else:
                row["status"] = "present" if observed else "missing"
        except Exception:  # noqa: BLE001 - doctor inventory degrades to unknown
            row["status"] = "unknown"
            row["reason"] = "inventory_failed"
        if row["status"] == "unknown" and "reason" not in row:
            row["reason"] = "inventory_failed"
        if row["status"] == "missing":
            row["fix"] = fix_sentence(name, deployment=deployment)
        rows.append(row)
    return rows
