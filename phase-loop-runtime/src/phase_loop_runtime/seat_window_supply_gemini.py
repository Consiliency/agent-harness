"""Gemini's window supplier (K-1 contract §4.1, §10.A).

It re-exports ``seat_jail_qualification``'s frozen interface names and calls the existing
Gemini argv and stream helpers; it edits neither module. Names are resolved at use, so
Gemini's W1 path reaches exactly the objects it always has.
"""
from __future__ import annotations

from typing import Sequence

_REEXPORTED = ("plant_layout", "build_qualification_input", "definition_probe",
               "ContextBinding", "ContainmentInputs", "reduce_containment",
               "arm_watch", "seed_runtime_plants")

#: Plugin forms Gemini's help gate chooses between (I-15).
plugin_forms = ("nested", "plugin_json")
#: Gemini ages its expired copy inside its own prepare function
#: (``_prepare_jailed_gemini(credential="expired")``), so the kit applies no transform.
copy_transform = None

_NONE_KINDS = frozenset({"help", "plugin_validation", "tree_control", "runtime_control"})


def __getattr__(name: str):
    if name in _REEXPORTED:
        from . import seat_jail_qualification
        return getattr(seat_jail_qualification, name)
    raise AttributeError(name)


def __dir__():
    return sorted({*globals(), *_REEXPORTED})


def credential_mode(kind: str) -> str:
    if kind == "expired_copy":
        return "expired"
    return "none" if kind in _NONE_KINDS else "live"


def host_path_map(seat, *, credential: bool):
    from . import panel_invoker, seat_jail_qualification
    return panel_invoker._window_host_paths(seat_jail_qualification, seat, credential=credential)


def launch_command(kind: str, *, qualification_input=None, model: str,
                   plugin_paths: Sequence[str] = ()) -> tuple[tuple[str, ...], ...]:
    """Every argv one launch spawns, in order: the existing Gemini forms, unchanged."""
    from . import panel_invoker, seat_jail
    if kind == "help":
        return ((f"{seat_jail.SEAT_BIN}/gemini", "--help"),)
    if kind == "plugin_validation":
        return tuple((f"{seat_jail.SEAT_BIN}/gemini", "plugin", "validate", path, "--strict",
                      "--json") for path in plugin_paths)
    return (tuple(panel_invoker._window_control_command(kind, model)),)


def stream_facts(raw_stdout: str):
    from . import panel_invoker
    return panel_invoker._window_stream_facts(raw_stdout)


def terminal(observation) -> str:
    """§5.5's closed class for one launch result."""
    error = getattr(observation, "error", None)
    if getattr(observation, "timed_out", False):
        return "timeout"
    if error in {"proxy_unavailable", "fence_unacknowledged"}:
        return "proxy_failure"
    if error in {"jail_unavailable", "watch_unavailable", "bridge_wait_timeout"}:
        return "jail_failure"
    if error == "credential_unavailable":
        return "not_ready"
    if error is not None:
        return "other_failure"
    status = getattr(observation, "status", "NONE")
    if status == "NONE":
        return "stream_incomplete"
    if status == "SUCCESS" and getattr(observation, "model_turn", None) is True:
        return "completed"
    if (getattr(observation, "kind", None) == "expired_copy" and status == "FAILURE"
            and getattr(observation, "model_turn", None) is not True):
        return "refused_intended"
    return "other_failure"


def scan_secrets(seat) -> tuple[bytes, ...]:
    from . import panel_invoker
    return panel_invoker._jailed_gemini_secrets(seat)


def measure_credential_scope(seat):
    """Gemini's scope is measured by the containment reducer from the issuer response."""
    return None


def refresh_detected(seat):
    """Gemini's refresh is detected by the containment reducer from the seat scan."""
    return None


def token_endpoint(event) -> bool:
    return (getattr(event, "method", None) == "POST"
            and getattr(event, "host", None) == "oauth2.googleapis.com")


def bracket_steps():
    """``None``: Gemini runs ``seat_jail_qualification.run_bracket``'s own steps."""
    return None
