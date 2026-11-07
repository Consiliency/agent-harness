"""Read-only admission verdicts shared by doctor and review-seat preparation."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Callable, Literal, Mapping

from .executable_dependency import ExecutableDependencyError


Status = Literal["admits", "refuses", "unknown"]
Reason = Literal["platform_unsupported", "inventory_failed", "launch_measurement", "provider_absent"]


@dataclass(frozen=True)
class Verdict:
    leg: str
    status: Status
    code: str | None = None
    fix: str | None = None
    reason: Reason | None = None


Gate = Callable[[str, Mapping[str, str], bool], Verdict | None]
_GATES: dict[str, list[Gate]] = {}
_LEGACY_LEGS = ("claude", "gemini")


def register(leg: str, gate: Gate) -> None:
    """Append one vendor gate, idempotently for the same callable."""

    if not isinstance(leg, str) or not leg:
        raise ValueError("invalid seat leg")
    gates = _GATES.setdefault(leg, [])
    if gate not in gates:
        gates.append(gate)


def _profile_module():
    try:
        from . import seat_profiles
    except ImportError:
        return None
    return seat_profiles


def _profile_for(leg: str):
    module = _profile_module()
    return None if module is None else module.profile_for(leg)


def registered_legs() -> tuple[str, ...]:
    legs = set(_LEGACY_LEGS) | set(_GATES)
    module = _profile_module()
    if module is not None:
        legs.update(module.registered_legs())
    return tuple(sorted(legs))


def _fix(code: str | None) -> str | None:
    if code is None:
        return None
    from . import seat_jail

    notice = seat_jail.render_notice(code, "")
    return None if notice is None else notice.fix


def _refuses(leg: str, code: str) -> Verdict:
    return Verdict(leg, "refuses", code=code, fix=_fix(code))


def _pass_record(leg: str, qualification_key=None) -> Verdict | None:
    from . import seat_jail

    try:
        key = qualification_key
        if key is None:
            key = seat_jail.jail_profile_digest(leg)
        passed, reason = seat_jail.pass_record_verdict(key)
    except Exception:  # noqa: BLE001 - an unreadable inventory is a doctor state
        return Verdict(leg, "unknown", reason="inventory_failed")
    if passed:
        return None
    if reason.startswith("store_unsafe:"):
        from . import seat_jail_autoqualify

        return Verdict(
            leg,
            "refuses",
            code="seat_jail_qualification_failed",
            fix=seat_jail_autoqualify.fix_for("store_unsafe"),
        )
    return Verdict(leg, "unknown", reason="launch_measurement")


def _managed_authority(leg: str, subject, profile) -> Verdict | object | None:
    """Gate G-A: open the pinned authority and admit the profile projection.

    Launch evaluates this after the egress step and before the pass record
    (``seat_route._projection_for_launch``), so the doctor does too.
    """
    from os import close as close_fd
    from types import SimpleNamespace

    from . import seat_subject
    from .seat_qualification_key import admit_profile_projection

    try:
        descriptor, expected = seat_subject.open_managed_authority(subject)
        dependency = None
        projection = None
        try:
            dependency = admit_profile_projection(
                profile,
                SimpleNamespace(
                    requirement=subject.requirement,
                    borrowed_authority_fd=descriptor,
                    expected_authority_sha256=expected,
                ),
            )
            if dependency is not None:
                projection = SimpleNamespace(
                    projection_digest=dependency.projection_digest,
                )
        finally:
            try:
                if dependency is not None:
                    dependency.close()
            finally:
                close_fd(descriptor)
    except ExecutableDependencyError as exc:
        return _refuses(leg, exc.code)
    except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
        return Verdict(leg, "unknown", reason="inventory_failed")
    return projection


def _profile_egress(leg: str, profile, execute: bool) -> tuple[Verdict | None, str | None]:
    """Evaluate L7 and return the digest production binds into the launch key."""

    if profile.allowlist_id is None:
        from . import seat_route

        try:
            exception = seat_route.load_route_policy().exceptions.get(profile.vendor)
            if exception is None or exception.kind != "open egress":
                return _refuses(leg, "seat_egress_allowlist_missing"), None
            if seat_route._now() >= exception.expiry:
                return _refuses(leg, "seat_route_exception_expired"), None
        except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
            return Verdict(leg, "unknown", reason="inventory_failed"), None
        return None, None

    if not execute:
        return Verdict(leg, "unknown", reason="launch_measurement"), None

    from . import seat_egress_proxy

    try:
        unavailable = getattr(seat_egress_proxy, "unavailable_code", None)
        code = unavailable() if unavailable is not None else (
            "gemini_seat_egress_unavailable"
            if seat_egress_proxy.unavailable_reason() is not None
            else None
        )
        if code is not None:
            return _refuses(leg, code), None
        digest = seat_egress_proxy.allowlist_ref(profile.allowlist_id).content_digest
    except seat_egress_proxy.EgressLayerUnavailable as exc:
        return _refuses(leg, exc.code), None
    except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
        return Verdict(leg, "unknown", reason="inventory_failed"), None
    return None, digest


def _base_verdict(leg: str, env: Mapping[str, str], execute: bool) -> Verdict | None:
    from . import seat_jail, seat_subject

    profile = _profile_for(leg)

    for gate in _GATES.get(leg, ()):
        try:
            result = gate(leg, env, execute)
        except Exception:  # noqa: BLE001
            return Verdict(leg, "unknown", reason="inventory_failed")
        if result is not None:
            return result

    if profile is not None or leg in _LEGACY_LEGS:
        try:
            code = seat_jail.seat_sandbox_capable()
        except Exception:  # noqa: BLE001
            return Verdict(leg, "unknown", reason="inventory_failed")
        if code is not None:
            return _refuses(leg, code)

        if profile is not None:
            if profile.recorded_stop is not None:
                return _refuses(leg, profile.recorded_stop)
            try:
                credential_present = profile.credential_present()
            except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
                return Verdict(leg, "unknown", reason="inventory_failed")
            if not credential_present:
                return _refuses(leg, profile.credential_missing_code)
            for precondition in profile.preconditions:
                try:
                    code = precondition.check()
                except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
                    return Verdict(leg, "unknown", reason="inventory_failed")
                if code is not None:
                    return _refuses(leg, code)
            has_egress = profile.allowlist_id is not None
        elif leg == "claude":
            try:
                credential_present = seat_jail._claude_credential_present()
            except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
                return Verdict(leg, "unknown", reason="inventory_failed")
            if not credential_present:
                return _refuses(leg, "claude_seat_token_missing")
            has_egress = False
        else:
            try:
                credential_present = seat_jail.gemini_operator_credential_present()
            except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
                return Verdict(leg, "unknown", reason="inventory_failed")
            if not credential_present:
                return _refuses(leg, "gemini_seat_credential_missing")
            has_egress = True

        allowlist_digest = None
        if profile is not None:
            egress, allowlist_digest = _profile_egress(leg, profile, execute)
            if egress is not None:
                return egress
        elif has_egress:
            if not execute:
                return Verdict(leg, "unknown", reason="launch_measurement")
            from . import seat_egress_proxy

            unavailable = getattr(seat_egress_proxy, "unavailable_code", None)
            code = unavailable() if unavailable is not None else (
                "gemini_seat_egress_unavailable"
                if seat_egress_proxy.unavailable_reason() is not None
                else None
            )
            if code is not None:
                return _refuses(leg, code)

        try:
            subject = seat_subject.resolve_seat_subject(leg, env)
        except FileNotFoundError:
            return Verdict(leg, "unknown", reason="provider_absent")
        except ExecutableDependencyError as exc:
            return _refuses(leg, exc.code)
        except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
            return Verdict(leg, "unknown", reason="inventory_failed")
        if subject.source == "managed_release" and profile is None:
            return Verdict(leg, "unknown", reason="inventory_failed")

        projection = None
        if profile is not None and subject.source == "managed_release":
            managed = _managed_authority(leg, subject, profile)
            if isinstance(managed, Verdict):
                return managed
            projection = managed

        qualification_key = None
        if profile is not None:
            from .seat_qualification_key import key_for_launch

            try:
                variant = None
                if profile.variant is not None:
                    variant, _code = profile.variant(env)
                qualification_key = key_for_launch(
                    profile,
                    variant=variant,
                    allowlist_digest=allowlist_digest,
                    projection=projection,
                )
            except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
                return Verdict(leg, "unknown", reason="inventory_failed")

        passed = _pass_record(leg, qualification_key)
        if passed is not None:
            return passed

    else:
        try:
            subject = seat_subject.resolve_seat_subject(leg, env)
        except FileNotFoundError:
            return Verdict(leg, "unknown", reason="provider_absent")
        except ExecutableDependencyError as exc:
            return _refuses(leg, exc.code)
        except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
            return Verdict(leg, "unknown", reason="inventory_failed")

    if leg == "claude":
        from . import claude_seat_transport

        try:
            _transport, refusal = claude_seat_transport.resolve_jailed_claude_transport(env)
        except Exception:  # noqa: BLE001 - doctor inventory degrades rather than raising
            return Verdict(leg, "unknown", reason="inventory_failed")
        if refusal is not None:
            return _refuses(leg, refusal)

    if leg == "gemini":
        from .agy_qualification import admission_verdict

        agy = admission_verdict(env, subject.subject_path, execute=execute)
        return Verdict(leg, agy.status, agy.code, _fix(agy.code), agy.reason)
    if leg == "grok":
        if not execute:
            return Verdict(leg, "unknown", reason="launch_measurement")
        from . import panel_invoker
        from .seat_jail import SeatSandboxRefused

        try:
            panel_invoker.require_grok_admission(["grok", "-p", "doctor"], env)
        except SeatSandboxRefused as exc:
            return _refuses(leg, exc.code)
    return None


def verdict(leg: str, env: Mapping[str, str], *, execute: bool = False) -> Verdict:
    """Evaluate the same ordered predicates used before a seat launches."""

    if not sys.platform.startswith("linux"):
        return Verdict(leg, "unknown", reason="platform_unsupported")
    if leg not in registered_legs():
        return Verdict(leg, "unknown", reason="provider_absent")
    base = _base_verdict(leg, env, execute)
    if base is not None:
        return base
    return Verdict(leg, "admits")
