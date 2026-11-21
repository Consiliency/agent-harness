"""``phase-loop seat-window status --vendor grok``: is this grok build measured, and should
a host move onto an update? (GROKROLL §3, §5.1)

    phase-loop seat-window status --vendor grok
        [--binary <path> | --binary-digest <sha256> | --release-version <x.y.z>]
        [--candidate <path> | --candidate-digest <sha256> | --candidate-version <x.y.z>]
        [--require-route review|sealed|staged]...   [--schema v1]   [--exit-code]

One ``grok_seat_status.v1`` object on stdout. No network or model call, no provider binary
executed, nothing written and no directory created. A path is opened with
``O_NOFOLLOW | O_NONBLOCK``, must be a regular file of at most ``MAX_BINARY_BYTES`` that
begins with the ELF magic, and is hashed through that one descriptor; if its ``fstat``
differs before and after, the query fails rather than guessing.

Exit status: 0 whenever an answer was printed; 2 for a usage error; 3 with a
``status_unavailable`` error object when the query itself failed. With ``--exit-code``, 1
replaces 0 when the subject is not measured or the decision is ``hold``.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .. import grok_tool_surface as gts
from . import catalog as releases
from . import evidence as ev

SCHEMA = "grok_seat_status.v1"
SCHEMAS = ("v1",)
ELF_MAGIC = b"\x7fELF"
#: The ``detail`` codes of a ``status_unavailable`` error, per role (§3.3).
FAILURES = ("unreadable", "not_regular", "changed", "too_large", "not_native")
DETAILS = tuple(f"{role}_{failure}" for role in ("subject", "candidate") for failure in FAILURES)
#: An answer cannot be given without the running launch context (its allow-list missing).
CONTEXT_UNAVAILABLE = "context_unavailable"
ACTIONS = ("advance", "hold")
REASONS = ("inputs_invalid", "candidate_unresolved", "candidate_evidence_invalid",
           "candidate_revoked", "subject_evidence_invalid", "same_build", "candidate_measured",
           "candidate_partial", "subject_revoked", "candidate_unmeasured",
           "first_install_unmeasured", "no_measured_build")
_CHUNK = 1 << 20


class StatusUnavailable(Exception):
    """The query itself failed; ``detail`` is one of :data:`DETAILS`."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UsageError(ValueError):
    """Conflicting or malformed selectors (exit 2)."""


def hash_path(path: str | os.PathLike[str], role: str) -> str:
    """The sha256 of the native binary at ``path``, read through one no-follow,
    non-blocking descriptor whose ``fstat`` must not change while it is read."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                             | getattr(os, "O_NOCTTY", 0))
    except OSError as exc:
        import errno

        if exc.errno == errno.ELOOP:
            raise StatusUnavailable(role + "_not_regular") from None
        raise StatusUnavailable(role + "_unreadable") from None
    try:
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise StatusUnavailable(role + "_not_regular")
            if before.st_size > releases.MAX_BINARY_BYTES:
                raise StatusUnavailable(role + "_too_large")
            digest = sha256()
            head = b""
            size = 0
            while chunk := os.read(descriptor, _CHUNK):
                if len(head) < len(ELF_MAGIC):
                    head = (head + chunk)[:len(ELF_MAGIC)]
                size += len(chunk)
                if size > before.st_size:  # it grew while read: never read it to the bound
                    raise StatusUnavailable(role + "_changed")
                if size > releases.MAX_BINARY_BYTES:
                    raise StatusUnavailable(role + "_too_large")
                digest.update(chunk)
            after = os.fstat(descriptor)
        except OSError:
            raise StatusUnavailable(role + "_unreadable") from None
    finally:
        os.close(descriptor)
    if _state(before) != _state(after) or size != after.st_size:
        raise StatusUnavailable(role + "_changed")
    if head != ELF_MAGIC:
        raise StatusUnavailable(role + "_not_native")
    return digest.hexdigest()


def _state(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def default_subject_path() -> str | None:
    """The binary a grok seat would launch on this host, by the production resolver
    (``panel_invoker._seat_provider_source``); ``None`` when no grok is installed. A
    launcher the resolver does not follow is returned as itself, and then fails the ELF
    check (assumption A1) instead of being reported by its own digest."""
    from .. import panel_invoker as panel

    try:
        return panel._seat_provider_source("grok", os.environ)[1]
    except FileNotFoundError as exc:
        if exc.args[:1] == ("seat_provider_unavailable",):
            return None
        raise StatusUnavailable("subject_unreadable") from None
    except Exception:  # noqa: BLE001 - an unverifiable bind source, a broken link
        raise StatusUnavailable("subject_unreadable") from None


def _forms() -> dict[str, list[str]]:
    from .. import panel_invoker as panel

    forms = panel.grok_runtime_forms(model=gts.MEASUREMENT_MODEL, effort=gts.MEASUREMENT_EFFORT)
    return {route: list(forms[route]) for route in gts.MEASURED_ROUTES}


def _running_context() -> str:
    try:
        digest = gts.context_digest()
    except Exception:  # noqa: BLE001 - the grok-review allow-list is missing
        raise StatusUnavailable(CONTEXT_UNAVAILABLE) from None
    if not releases.is_digest(digest):
        raise StatusUnavailable(CONTEXT_UNAVAILABLE)
    return digest


def _selected(role: str, path, digest, version, sources: ev.Sources,
              *, default: bool) -> tuple[bool, str | None, str | None]:
    """``(present, digest, version)`` for one selector set; ``present`` is false only when
    no build is named (no candidate selector, or no grok installed)."""
    catalog = sources.members  # None unless the gate is attested (GROKROLL E1)
    if path is not None:
        found = hash_path(path, role)
    elif digest is not None:
        found = digest
    elif version is not None:
        member = None if catalog is None else catalog.by_version(version)
        return True, (None if member is None else member["binary_sha256"]), version
    elif default:
        resolved = default_subject_path()
        if resolved is None:
            return False, None, None
        found = hash_path(resolved, role)
    else:
        return False, None, None
    member = None if catalog is None else catalog.by_digest(found)
    return True, found, (None if member is None else member["version"])


def _build_object(sources: ev.Sources, build: ev.Build, version: str | None) -> dict[str, Any]:
    catalog = sources.members
    member = None if catalog is None or build.digest is None else catalog.by_digest(build.digest)
    return {"binary_sha256": build.digest, "version": version,
            "release": "member" if member is not None else "unknown", "state": build.state,
            "measured": build.measured, "routes": [route.as_dict() for route in build.routes],
            "context_digest": build.context_digest, "measured_at": build.measured_at}


def decide(*, inputs_invalid: bool, subject: Mapping[str, Any] | None,
           candidate: Mapping[str, Any]) -> dict[str, str]:
    """The decision table (§5.1), first matching row. Row 7 is the only ``advance``."""
    def hold(reason: str) -> dict[str, str]:
        return {"action": "hold", "reason": reason}

    state = candidate["state"]
    if inputs_invalid:
        return hold("inputs_invalid")
    if state == "unresolved":
        return hold("candidate_unresolved")
    if state == "invalid":
        return hold("candidate_evidence_invalid")
    if state == "revoked":
        return hold("candidate_revoked")
    if subject is not None and subject["state"] == "invalid":
        return hold("subject_evidence_invalid")
    if subject is not None and subject["binary_sha256"] is not None and \
            subject["binary_sha256"] == candidate["binary_sha256"]:
        return hold("same_build")
    if state == "measured":
        return {"action": "advance", "reason": "candidate_measured"}
    if state == "partial":
        return hold("candidate_partial")
    if subject is not None and subject["state"] == "revoked":
        return hold("subject_revoked")
    if subject is not None and subject["state"] in ("measured", "partial"):
        return hold("candidate_unmeasured")
    if subject is None:
        return hold("first_install_unmeasured")
    return hold("no_measured_build")


def _target(entry: Mapping[str, Any]) -> dict[str, str]:
    return {"version": entry["version"], "binary_sha256": entry["binary_sha256"],
            "tarball_integrity": entry["tarball_integrity"]}


def _targets(sources: ev.Sources, required: Sequence[str],
             subject_version: str | None) -> tuple[dict | None, dict | None]:
    """``advance_to`` and ``rollback_to`` (§3.3): only members whose full evaluation is
    ``measured``; both ``null`` on an invalid input."""
    if sources.inputs_invalid or sources.members is None:
        return None, None
    advance = rollback = None
    floor = None
    if subject_version is not None and releases.is_version(subject_version):
        floor = releases.version_key(subject_version)
    for entry in sources.members.newest_first():
        if advance is not None and (floor is None or rollback is not None):
            break
        if not ev.evaluate(sources, entry["binary_sha256"], required).measured:
            continue
        if advance is None:
            advance = _target(entry)
        if floor is not None and rollback is None and releases.version_key(entry["version"]) < floor:
            rollback = _target(entry)
    return advance, rollback


def query(*, binary=None, binary_digest=None, release_version=None, candidate=None,
          candidate_digest=None, candidate_version=None, require_routes: Sequence[str] = (),
          record_root=None) -> dict[str, Any]:
    """The ``grok_seat_status.v1`` object, or :class:`StatusUnavailable`."""
    if sum(value is not None for value in (binary, binary_digest, release_version)) > 1:
        raise UsageError("at most one subject selector")
    if sum(value is not None for value in (candidate, candidate_digest, candidate_version)) > 1:
        raise UsageError("at most one candidate selector")
    for value in (binary_digest, candidate_digest):
        if value is not None and not releases.is_digest(value):
            raise UsageError("a digest selector is 64 lowercase hex")
    for value in (release_version, candidate_version):
        if value is not None and not releases.is_version(value):
            raise UsageError("a version selector is MAJOR.MINOR.PATCH")
    if any(route not in gts.MEASURED_ROUTES for route in require_routes):
        raise UsageError("unknown route")
    required = tuple(route for route in gts.MEASURED_ROUTES
                     if route in (*ev.REQUIRED_ROUTES, *require_routes))
    context = _running_context()
    with ev.Sources(context_digest=context, forms=_forms(), record_root=record_root) as sources:
        has_subject, subject_digest, subject_version = _selected(
            "subject", binary, binary_digest, release_version, sources, default=True)
        has_candidate, candidate_digest_, candidate_version_ = _selected(
            "candidate", candidate, candidate_digest, candidate_version, sources, default=False)
        subject_object = None
        if has_subject:
            subject_object = _build_object(
                sources, ev.evaluate(sources, subject_digest, required), subject_version)
        candidate_object = decision = None
        if has_candidate:
            candidate_object = _build_object(
                sources, ev.evaluate(sources, candidate_digest_, required), candidate_version_)
            decision = decide(inputs_invalid=sources.inputs_invalid, subject=subject_object,
                              candidate=candidate_object)
        member_version = None
        if subject_object is not None and subject_object["release"] == "member":
            member_version = subject_object["version"]
        advance_to, rollback_to = _targets(sources, required, member_version)
        return {"schema": SCHEMA, "vendor": "grok", "context_digest": context,
                "inputs": sources.inputs, "required_routes": list(required),
                "subject": subject_object, "candidate": candidate_object, "decision": decision,
                "advance_to": advance_to, "rollback_to": rollback_to}


def unavailable(detail: str) -> dict[str, str]:
    return {"schema": SCHEMA, "error": "status_unavailable", "detail": detail}


def cli_main(args) -> int:
    """``seat-window status``: print one object and return the exit status of §3.3."""
    if getattr(args, "vendor", "grok") != "grok" or getattr(args, "schema", "v1") not in SCHEMAS:
        print("seat-window status: only --vendor grok and --schema v1", file=sys.stderr)
        return 2
    try:
        result = query(binary=args.binary, binary_digest=args.binary_digest,
                       release_version=args.release_version, candidate=args.candidate,
                       candidate_digest=args.candidate_digest,
                       candidate_version=args.candidate_version,
                       require_routes=tuple(args.require_route or ()))
    except UsageError as exc:
        print(f"seat-window status: {exc}", file=sys.stderr)
        return 2
    except StatusUnavailable as exc:
        print(json.dumps(unavailable(exc.detail), sort_keys=True))
        return 3
    print(json.dumps(result, sort_keys=True))
    if getattr(args, "exit_code", False):
        subject = result["subject"]
        decision = result["decision"]
        if subject is None or not subject["measured"] or (
                decision is not None and decision["action"] == "hold"):
            return 1
    return 0
