"""Namespaced standalone route preflight, before envelope I/O or imports."""
from .executable_dependency import ExecutableDependencyError
from .executable_dependency_startup import refuse_unwired_dependency_route
from .supervised_launch import Refused


def classify_supervised_command(command: str) -> str:
    return "provider_free" if command == "supervised-status" else "dependency_unwired"


def preflight_supervised_route(command: str) -> Refused | None:
    classification = classify_supervised_command(command)
    if classification != "provider_free":
        try:
            refuse_unwired_dependency_route(command)
        except ExecutableDependencyError as exc:
            return Refused(exc.code)
    if command not in {"supervised-launch", "supervised-cancel", "supervised-status"}:
        return Refused("dependency_route_unwired")
    return None
