"""The jailed Grok launch context ``grok_jail_context.v1`` and its gate (GROK SL-3).

Frozen contract: ``plans/artifacts/grok-jail-tool-surface-contract-v1.md`` ("the jail
contract"), §2 to §5.1; plan ``plans/phase-plan-v1-seats-GROK.md``, IF-0-GROK-3.

Installing this module opens SL-2's closed gate only in name: :func:`precondition_code`
passes only when all five eligibility conditions of the jail contract §2.4 hold, and three
of them are records no lane can write (the owner's masked-projection confirmation, the
hosted boundary check, an admitted jailed measurement). Until they exist every Grok
launch still stops at L6 with ``grok_tool_surface_unverified``.

The final verifier, :func:`verify_jail_launch_context`, runs at the spawn boundary of the
jailed leg (``panel_invoker._run_leg_with_liveness``'s jailed branch) against the objects
about to be spawned and issues the only mark that branch admits for a Grok argv. The
unjailed context ``grok_seat_context.v1`` and ``grok_tool_surface.context_digest()`` are
not touched by anything here.
"""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import json
import os
import posixpath
import re
import stat
import sys
from dataclasses import dataclass, field
from hashlib import sha256
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from . import grok_tool_surface as _gts
from . import seat_profile_grok as _profile

JAIL_CONTEXT = "grok_jail_context.v1"
REFUSED = "grok_tool_surface_unverified"
UNAVAILABLE = "seat_profile_unavailable"
#: Eligibility condition 1: the enforcement this build installs, naming the §2.3 list
#: revision it checks (option A, jail contract revision r5).
_ENFORCEMENT_REVISION = "grok_jail_enforcement.v1:mounts=option-a-r5"
ENFORCEMENT = _ENFORCEMENT_REVISION
COMPOSITION = "seat_jail.build_seat_jail+profile:grok"
SEAT_CONFIG_PROJECTION = "ro-staged-dotdir"
#: The production model and effort: the one entry the pinned seat config declares.
PRODUCTION_MODEL = _gts.MEASUREMENT_MODEL
PRODUCTION_EFFORT = _gts.MEASUREMENT_EFFORT
SEAT_CWD = _profile.SEAT_TREE
MODES = ("board", "measurement")

CONFIRMATION_SCHEMA = "grok_jail_confirmation.v1"
BOUNDARY_SCHEMA = "grok_jail_boundary.v1"
HOST_RECORD_SCHEMA = "grok_jail_tool_surface_measurement.v1"
CATALOG_SCHEMA = "grok_jail_tool_surface_catalog.v1"
CATALOG_NAME = "grok_jail_tool_surfaces.json"
ATTEMPTS_SCHEMA = "grok_jail_tool_surface_attempts.v1"
ADMISSION_SCHEMA = "grok_jail_measurement_admission.v1"
LAUNCH_DIGEST_SCHEMA = "grok_jail_launch.v1"
RECORD_MAX_BYTES = 16384
CATALOG_MAX_BYTES = 256 * 1024
ARCHES = ("x86_64", "aarch64")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:/._?=&%#@+-]{0,255}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ISSUER = object()
#: The eligibility conditions of §2.4, in order.
CONDITIONS = ("enforcement", "protection", "confirmation", "boundary", "record")
_CONFIRMATION_OUTCOME = MappingProxyType({
    "inference_request_reached": True, "settings_requested": False,
    "models_requested": False, "staged_unchanged": True,
})


class JailRefused(ValueError):
    """One rule of the jailed context failed; mapped to a typed refusal by every caller."""


def _refused(code: str = REFUSED, detail: str = ""):
    from .seat_jail import SeatSandboxRefused

    return SeatSandboxRefused(code, detail) if detail else SeatSandboxRefused(code)


def _require(condition: bool, detail: str = "refused") -> None:
    if not condition:
        raise JailRefused(detail)


def _hex64(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


# --- Inputs and drift (jail contract §2.3, §2.4 "Drift") -----------------------------------


def staged_config_bytes() -> bytes:
    """The jailed seat's config bytes, asserted equal to E8-A's ``seat_config()`` so the two
    projections cannot drift (§2.3 "Code ownership"). A drift that makes either source raise
    (E8-A's ``_Refused`` is a ``ValueError``) is ``seat_profile_unavailable`` (SL-1 N1)."""
    from . import seat_grok_credential as credential
    from .seat_jail import SeatSandboxRefused

    try:
        unjailed = _gts.seat_config()
        jailed = credential.seat_config_bytes()
    except SeatSandboxRefused as exc:
        raise _refused(UNAVAILABLE, "seat config off its pin") from exc
    except ValueError as exc:
        raise _refused(UNAVAILABLE, "seat config off its pin") from exc
    if (jailed != unjailed or sha256(jailed).hexdigest() != _gts.SEAT_CONFIG_SHA256
            or credential.SEAT_CONFIG_SHA256 != _gts.SEAT_CONFIG_SHA256):
        raise _refused(UNAVAILABLE, "the jailed and unjailed seat configs differ")
    return jailed


def protection_drift(image_sha256: str) -> str | None:
    """``None`` when the image's protection table classifies exactly E8-A's fixed inputs,
    their exclusions, the managed and child-absent policy paths and main's discovery paths;
    else a short reason. An image with no table entry has no eligible ``staged``."""
    table = _profile.JAIL_PROTECTION.get(image_sha256)
    if table is None:
        return "no protection table for the image"
    home_and_absolute = [path for scope, path, _treatment in table if scope != _profile.TREE]
    tree = [path for scope, path, _treatment in table if scope == _profile.TREE]
    expected = (*_gts.SEAT_FIXED_INPUTS, *_gts.SEAT_FIXED_INPUT_EXCLUSIONS)
    if sorted(home_and_absolute) != sorted(set(expected)) or len(home_and_absolute) != len(
            set(expected)):
        return "fixed inputs differ"
    if sorted(tree) != sorted(_gts.DISCOVERY_PATHS) or tuple(_profile.DISCOVERY_PATHS) != tuple(
            _gts.DISCOVERY_PATHS):
        return "discovery paths differ"
    absent = {path for scope, path, treatment in table
              if treatment == _profile.ABSENT_OUTSIDE_WRITABLE_MOUNTS}
    if absent != {*_gts.MANAGED_CONFIG_PATHS, *_gts.CHILD_ABSENT_POLICY_PATHS}:
        return "managed config paths differ"
    if any(treatment not in _profile.TREATMENTS for _scope, _path, treatment in table):
        return "unknown treatment"
    return None


def mounts_document() -> list[list[str]]:
    """§2.3's ordered mount list with role placeholders: what the context digest binds."""
    return [list(words) for words, _destination in _profile._ordered_mounts(
        "<provider-config>", "<home>", "<egress-ca>")]


def _environment_names() -> list[str]:
    from .seat_jail import seat_env

    return sorted(seat_env(_profile.LEG, token_fd=None, egress_proxy="<egress-proxy>"))


def jail_context_document(image_sha256: str) -> dict[str, object]:
    table = _profile.JAIL_PROTECTION.get(image_sha256, ())
    return {
        "schema": JAIL_CONTEXT,
        "composition": COMPOSITION,
        "home": _profile.SEAT_HOME,
        "seat_config": {"path": _gts.SEAT_CONFIG_RELATIVE, "sha256": _gts.SEAT_CONFIG_SHA256,
                        "projection": SEAT_CONFIG_PROJECTION},
        "mounts": mounts_document(),
        "protection": {"image_sha256": image_sha256,
                       "table": [list(row) for row in table]},
        "environment": {"allowed": _environment_names(),
                        "forbidden_prefixes": list(_gts.FORBIDDEN_ENVIRONMENT_PREFIXES)},
        "managed_config": list(_gts.MANAGED_CONFIG_PATHS),
        "child_absent_policy": list(_gts.CHILD_ABSENT_POLICY_PATHS),
        "egress": {"allowlist_id": _profile.GROK_PROFILE.allowlist_id,
                   "content_digest": _gts.egress_allowlist_digest()},
    }


def jail_context_digest(image_sha256: str) -> str:
    """sha256 of the canonical JSON of ``grok_jail_context.v1`` for one image (§2.2)."""
    return sha256(_canonical(jail_context_document(image_sha256))).hexdigest()


# --- The production argv (§2.1 "Argv") -----------------------------------------------------


def production_command(argv0: str = "/seat/bin/grok") -> tuple[str, ...]:
    from .seat_route_contract import ArgvInputs

    return _profile.jailed_grok_command(ArgvInputs(
        argv0, model=PRODUCTION_MODEL, effort=PRODUCTION_EFFORT))


def staged_argv_digest() -> str:
    """The record key's argv digest: ``staged``'s for the production model and effort."""
    from .panel_invoker import _grok_argv_digest, grok_runtime_forms

    return _grok_argv_digest(grok_runtime_forms(
        model=PRODUCTION_MODEL, effort=PRODUCTION_EFFORT)["staged"])


# --- The launch digest (§2.2) ---------------------------------------------------------------

_SESSIONS = f"{_profile.SEAT_GROK_DOTDIR}/sessions"
_SESSIONS_TMPFS = ("--perms", "1777", "--tmpfs", _SESSIONS)


def sink_source(home: str) -> str:
    """The measurement's sessions sink, ``<home>/.grok-rw/sessions`` (§5.1 item 3)."""
    return _profile.writable_source(home, "sessions")


def _home_of(jail) -> str:
    from .seat_jail import HOST_HOME_DIRNAME

    return str(Path(jail.review_dir) / HOST_HOME_DIRNAME)


def measurement_owner(jail) -> tuple[str, ...]:
    """The measurement's owner argv: production's with the sessions tmpfs replaced, in
    place, by the bind of the reservation's sink (the first declared difference)."""
    owner = list(jail.process_owner)
    for index in range(len(owner) - 3):
        if tuple(owner[index:index + 4]) == _SESSIONS_TMPFS:
            owner[index:index + 4] = ["--bind", sink_source(_home_of(jail)), _SESSIONS]
            return tuple(owner)
    raise JailRefused("no sessions mount to substitute")


def production_owner(jail, *, measurement: bool) -> tuple[str, ...]:
    """The owner argv with the declared sink bind substituted back to the production
    sessions tmpfs (``measurement=True``), refusing unless the owner differs from production
    by exactly that one bind at the tmpfs's position; the owner itself otherwise. The same
    single substitution :func:`launch_digest` makes and ``panel_invoker._require_qualified_jail``
    applies to a measurement jail (jail contract §5.1 r7)."""
    owner = list(jail.process_owner)
    if not measurement:
        return tuple(owner)
    bind = ("--bind", sink_source(_home_of(jail)), _SESSIONS)
    for index in range(len(owner) - 2):
        if tuple(owner[index:index + 3]) == bind:
            owner[index:index + 3] = list(_SESSIONS_TMPFS)
            return tuple(owner)
    raise JailRefused("the measurement owner carries no sink bind")


def launch_digest(jail, command, *, arch: str | None = None,
                  measurement: bool = False) -> str:
    """sha256 of the normalised **actual** owner argv and filter (``seat_jail``'s
    placeholder normalisation of per-launch directories, descriptors, the config, mask and
    CA sources and the proxy), the environment names, the argv digest and the pinned config
    digest. In a measurement the declared sink bind is substituted back first. Credential,
    ``agent_id`` and CA bytes are excluded: check 3 verifies them per launch."""
    from .panel_invoker import _grok_argv_digest
    from .seat_jail import actual_profile_digest, host_arch

    arch = arch or host_arch()
    normalised = dataclasses.replace(jail, process_owner=production_owner(
        jail, measurement=measurement))
    return sha256(_canonical({
        "schema": LAUNCH_DIGEST_SCHEMA,
        "arch": arch,
        "owner": actual_profile_digest(normalised, arch),
        "filter": jail.filter_digest,
        "environment": sorted(jail.env),
        "argv_digest": _grok_argv_digest(list(command)),
        "seat_config_sha256": _gts.SEAT_CONFIG_SHA256,
    })).hexdigest()


# --- Private records (§2.4 conditions 3 to 5, §3) -----------------------------------------


def confirmation_name(image_sha256: str) -> str:
    return f"grok-jail-confirmation-{image_sha256}.json"


def boundary_name(launch: str) -> str:
    return f"grok-jail-boundary-{launch}.json"


def host_record_name(binary_sha256: str) -> str:
    return f"grok-jail-surface-{binary_sha256}.json"


def attempts_name(binary_sha256: str) -> str:
    return f"grok-jail-surface-{binary_sha256}.attempts.json"


def receipt_name(binary_sha256: str, argv_digest: str) -> str:
    return f"grok-jail-tools-{binary_sha256}-{argv_digest}.json"


def _strict(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise JailRefused("duplicate member")
    return dict(pairs)


def _loads(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict)


def read_private(name: str, limit: int = RECORD_MAX_BYTES) -> dict | None:
    """One private record under the operator's record root, read with the TS contract §3.2
    file checks: the directory the operator's and 0700, the file a regular 0600 file of the
    operator's, opened without following a link and read with a bound. ``None`` on any
    refusal or absence."""
    from .president_adapter import private_record_root

    if Path(name).name != name or not name.endswith(".json"):
        return None
    try:
        directory = os.open(private_record_root(),
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            return None
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                                 | os.O_CLOEXEC, dir_fd=directory)
        except OSError:
            return None
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit):
                return None
            raw = os.read(descriptor, limit + 1)
        finally:
            os.close(descriptor)
    except OSError:
        return None
    finally:
        os.close(directory)
    try:
        _require(len(raw) <= limit)
        document = _loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    return document if type(document) is dict else None


def write_private(name: str, document: Mapping[str, object]) -> Path:
    """Write one private record (replacing an older one), through the operator record
    writer. The caller validates the document first."""
    from .president_adapter import private_record_root, write_private_record
    from .seat_jail import open_dir_nofollow

    root = private_record_root()
    if root.exists():
        directory = open_dir_nofollow(root)
        try:
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass
        finally:
            os.close(directory)
    return write_private_record(name, dict(document))


def _launch_digests(value: object) -> bool:
    return (type(value) is dict and bool(value) and set(value) <= set(ARCHES)
            and all(_hex64(item) for item in value.values()))


def check_confirmation(document: object, image_sha256: str) -> None:
    """Condition 3's record (``grok_jail_confirmation.v1``), bound to the image, its
    per-architecture ``launch_digest`` and the running ``jail_context_digest``."""
    _require(type(document) is dict and set(document) == {
        "schema", "image_sha256", "launch_digest", "jail_context_digest", "outcome",
        "approval_id", "approved_on"})
    assert isinstance(document, dict)
    _require(document["schema"] == CONFIRMATION_SCHEMA)
    _require(document["image_sha256"] == image_sha256 and _hex64(image_sha256))
    _require(_launch_digests(document["launch_digest"]))
    _require(document["jail_context_digest"] == jail_context_digest(image_sha256))
    _require(type(document["outcome"]) is dict
             and document["outcome"] == dict(_CONFIRMATION_OUTCOME))
    _require(type(document["approval_id"]) is str
             and _ID.fullmatch(document["approval_id"]) is not None)
    _require(type(document["approved_on"]) is str
             and _DATE.fullmatch(document["approved_on"]) is not None)


def check_boundary(document: object, launch: str, image_sha256: str) -> None:
    """Condition 4's record (``grok_jail_boundary.v1``): the hosted BA-J5 run, passed with
    no skipped case, bound to ``launch_digest`` and the running ``jail_context_digest``."""
    _require(type(document) is dict and set(document) == {
        "schema", "hosted_run", "head", "launch_digest", "jail_context_digest", "ba_j5",
        "skipped"})
    assert isinstance(document, dict)
    _require(document["schema"] == BOUNDARY_SCHEMA)
    _require(type(document["hosted_run"]) is str
             and _ID.fullmatch(document["hosted_run"]) is not None)
    _require(type(document["head"]) is str and _HEX40.fullmatch(document["head"]) is not None)
    _require(document["launch_digest"] == launch and _hex64(launch))
    _require(document["jail_context_digest"] == jail_context_digest(image_sha256))
    _require(document["ba_j5"] == "passed" and document["skipped"] == 0
             and type(document["skipped"]) is int)


_SURFACE_EXTRA = frozenset({"jail_context_digest", "launch_digest", "image_sha256"})
_CATALOG_EXTRA = frozenset({"confirmation", "boundary"})


def check_jail_surface(surface: object, *, catalog: bool = False) -> None:
    """A jailed surface: the TS contract §3.1 shape with ``context`` fixed to the jailed
    context, plus ``jail_context_digest``, per-architecture ``launch_digest`` and
    ``image_sha256``; a catalog entry may also carry the condition 3 and 4 objects."""
    _require(type(surface) is dict)
    assert isinstance(surface, dict)
    keys = set(surface)
    base = keys - _SURFACE_EXTRA - (_CATALOG_EXTRA if catalog else frozenset())
    _require(_SURFACE_EXTRA <= keys and surface.get("context") == JAIL_CONTEXT)
    _require(_hex64(surface["jail_context_digest"]) and _hex64(surface["image_sha256"])
             and _launch_digests(surface["launch_digest"]))
    plain = {key: surface[key] for key in base}
    plain["context"] = _gts.GROK_SEAT_CONTEXT  # reuse the TS contract's shape checks
    try:
        _gts._check_surface(plain)
    except ValueError as exc:
        raise JailRefused("surface shape") from exc


def load_catalog() -> dict[str, object]:
    """The shipped jailed catalog, read through ``importlib.resources``. A missing file is
    an empty catalog; any refusal voids it (``revoked`` cannot be known): ``None``."""
    try:
        resource = resources.files(__package__).joinpath("data", CATALOG_NAME)
        with resource.open("rb") as source:
            raw = source.read(CATALOG_MAX_BYTES + 1)
    except FileNotFoundError:
        return {"revoked": frozenset(), "surfaces": {}}
    except OSError:
        return None  # type: ignore[return-value]
    try:
        _require(len(raw) <= CATALOG_MAX_BYTES)
        document = _loads(raw)
        _require(type(document) is dict and set(document) == {"schema", "revoked", "surfaces"})
        assert isinstance(document, dict)
        _require(document["schema"] == CATALOG_SCHEMA)
        revoked = document["revoked"]
        _require(type(revoked) is list and all(_hex64(item) for item in revoked))
        surfaces: dict[str, Mapping[str, Any]] = {}
        _require(type(document["surfaces"]) is list)
        for surface in document["surfaces"]:
            check_jail_surface(surface, catalog=True)
            binary = surface["binary_sha256"]
            _require(binary not in surfaces and binary not in revoked)
            surfaces[binary] = surface
    except (ValueError, TypeError, RecursionError, UnicodeDecodeError):
        return None  # type: ignore[return-value]
    return {"revoked": frozenset(revoked), "surfaces": surfaces}


def load_host_record(binary_sha256: str) -> Mapping[str, Any] | None:
    from .seat_window import _host_digest

    document = read_private(host_record_name(binary_sha256))
    try:
        _require(document is not None and set(document) == {"schema", "host_digest", "surface"})
        assert document is not None
        _require(document["schema"] == HOST_RECORD_SCHEMA)
        _require(document["host_digest"] == _host_digest())
        check_jail_surface(document["surface"])
        _require(document["surface"]["binary_sha256"] == binary_sha256)
    except (ValueError, TypeError, KeyError):
        return None
    return document["surface"]


def _host_route_current(binary_sha256: str, argv_digest: str, route_digest: str) -> bool:
    """The jailed latest-attempt register (§3, TS contract §5.7 and BA-2 by name): a
    host-local route is consumable only while the register names it published from the
    latest attempt. A missing or unreadable register admits nothing."""
    from .seat_window import _host_digest

    document = read_private(attempts_name(binary_sha256))
    try:
        _require(document is not None and set(document) == {
            "schema", "binary_sha256", "host_digest", "attempts", "published"})
        assert document is not None
        _require(document["schema"] == ATTEMPTS_SCHEMA
                 and document["binary_sha256"] == binary_sha256
                 and document["host_digest"] == _host_digest())
        published = document["published"].get(argv_digest)
        latest = document["attempts"].get(argv_digest)
        _require(type(published) is dict and type(latest) is dict)
        return (published.get("grant") == latest.get("grant")
                and published.get("reservation") == latest.get("reservation")
                and published.get("surface_digest") == route_digest)
    except (ValueError, TypeError, AttributeError):
        return False


@dataclass(frozen=True)
class JailedSurface:
    surface: Mapping[str, Any]
    route: Mapping[str, Any]
    source: str
    surface_digest: str


def resolve_record(binary_sha256: str, argv_digest: str) -> JailedSurface | None:
    """The jailed record for ``(binary_sha256, argv_digest)`` by TS contract §3.2
    precedence (catalog first; a revoked digest or a void catalog voids every source)."""
    catalog = load_catalog()
    if catalog is None or not _hex64(binary_sha256) or binary_sha256 in catalog["revoked"]:
        return None

    def route_of(surface):
        if surface is None:
            return None
        return next((route for route in surface["routes"]
                     if route["argv_digest"] == argv_digest), None)

    shipped = catalog["surfaces"].get(binary_sha256)  # type: ignore[union-attr]
    route = route_of(shipped)
    if route is not None:
        return JailedSurface(shipped, route, "catalog", _gts.surface_digest(shipped, route))
    host = load_host_record(binary_sha256)
    route = route_of(host)
    if route is None:
        return None
    digest = _gts.surface_digest(host, route)
    if not _host_route_current(binary_sha256, argv_digest, digest):
        return None
    return JailedSurface(host, route, "host_local", digest)


def _expected_launch(binary_sha256: str, arch: str | None = None) -> str | None:
    """The production ``launch_digest`` the owner confirmed for this image on ``arch``."""
    from .seat_jail import host_arch

    arch = arch or host_arch()
    catalog = load_catalog() or {"surfaces": {}}
    sources = [read_private(confirmation_name(binary_sha256))]
    entry = catalog["surfaces"].get(binary_sha256)  # type: ignore[union-attr]
    if entry is not None and "confirmation" in entry:
        sources.append(entry["confirmation"])
    for document in sources:
        try:
            check_confirmation(document, binary_sha256)
        except (JailRefused, TypeError, KeyError):
            continue
        assert isinstance(document, dict)
        value = document["launch_digest"].get(arch)
        if value is not None:
            return value
    return None


def _boundary_passed(binary_sha256: str, launch: str) -> bool:
    catalog = load_catalog() or {"surfaces": {}}
    sources = [read_private(boundary_name(launch))]
    entry = catalog["surfaces"].get(binary_sha256)  # type: ignore[union-attr]
    if entry is not None and "boundary" in entry:
        sources.append(entry["boundary"])
    for document in sources:
        try:
            check_boundary(document, launch, binary_sha256)
            return True
        except (JailRefused, TypeError, KeyError):
            continue
    return False


def _admitted_record(binary_sha256: str, launch: str) -> JailedSurface | None:
    """Condition 5: a jailed record for the image and the ``staged`` argv digest,
    ``measured`` (it has a route) and admitted, whose digests are the running ones."""
    from .panel_invoker import _grok_tools_admitted

    record = resolve_record(binary_sha256, staged_argv_digest())
    if record is None:
        return None
    surface = record.surface
    from .seat_jail import host_arch

    if (surface["jail_context_digest"] != jail_context_digest(binary_sha256)
            or surface["image_sha256"] != binary_sha256
            or surface["launch_digest"].get(host_arch()) != launch
            or not _grok_tools_admitted(list(production_command()), list(record.route["tools"]))):
        return None
    return record


def eligibility(binary_sha256: str, *, through: int = 5) -> str | None:
    """The first failing condition of jail contract §2.4 (one of :data:`CONDITIONS`), or
    ``None``. ``through=4`` is the measurement's set (conditions 1 to 4, before
    ``--new-grant`` and ``--rehearse``); the board's L6 and final spawn take all five."""
    checking = "enforcement"
    try:
        from . import grok_jail_surface as installed

        if getattr(installed, "ENFORCEMENT", None) != _ENFORCEMENT_REVISION:
            return checking
        checking = "protection"
        if not _hex64(binary_sha256) or protection_drift(binary_sha256) is not None:
            return checking
        staged_config_bytes()
        checking = "confirmation"
        launch = _expected_launch(binary_sha256)
        if launch is None:
            return checking
        checking = "boundary"
        if not _boundary_passed(binary_sha256, launch):
            return checking
        checking = "record"
        if through >= 5 and _admitted_record(binary_sha256, launch) is None:
            return checking
    except Exception:  # noqa: BLE001 - every unknown closes the gate, named by its condition
        return checking
    return None


def staged_admission(binary_sha256: str) -> Mapping[str, object] | None:
    """The window kit's admission read (§4.3): the admitted jailed ``staged`` record and
    its binding digests, or ``None`` while any eligibility condition fails."""
    if eligibility(binary_sha256) is not None:
        return None
    launch = _expected_launch(binary_sha256)
    record = _admitted_record(binary_sha256, launch or "")
    if record is None or launch is None:
        return None
    return MappingProxyType({
        "context": JAIL_CONTEXT, "binary_sha256": binary_sha256,
        "argv_digest": staged_argv_digest(), "tools": tuple(record.route["tools"]),
        "surface_digest": record.surface_digest, "surface_source": record.source,
        "jail_context_digest": jail_context_digest(binary_sha256), "launch_digest": launch,
    })


# --- Jailed receipts (§3 "Receipts", BA-J3) -------------------------------------------------


def jail_receipt(record: JailedSurface, binary_sha256: str, launch: str) -> dict[str, object]:
    return {
        "schema": "tool_probe.v1", "binary_digest": binary_sha256,
        "argv_digest": staged_argv_digest(), "passed": True, "public_code": None,
        "tools": sorted(set(record.route["tools"])),
        "version_digest": record.surface["version_sha256"],
        "basis": "frozen_measurement", "surface_digest": record.surface_digest,
        "surface_source": record.source, "context": JAIL_CONTEXT,
        "context_digest": jail_context_digest(binary_sha256), "launch_digest": launch,
    }


def write_jail_receipt(binary_sha256: str) -> dict[str, object]:
    """Write the jailed probe receipt for the image's admitted ``staged`` record into the
    jailed receipt store only; an unjailed ``tool_probe.v1`` file is never touched."""
    launch = _expected_launch(binary_sha256)
    record = _admitted_record(binary_sha256, launch) if launch is not None else None
    if record is None or launch is None:
        return {"passed": False, "public_code": REFUSED}
    receipt = jail_receipt(record, binary_sha256, launch)
    write_private(receipt_name(binary_sha256, staged_argv_digest()), receipt)
    return receipt


def jail_receipt_matches(binary_sha256: str, launch: str) -> JailedSurface | None:
    """The jailed receipt for the image's ``staged`` argv, equal to what the record,
    re-resolved now, would issue. A withdrawn record, a replaced catalog route, a moved
    digest, an unjailed, legacy or listing receipt in its place: ``None``."""
    receipt = read_private(receipt_name(binary_sha256, staged_argv_digest()))
    record = _admitted_record(binary_sha256, launch)
    if receipt is None or record is None:
        return None
    return record if receipt == jail_receipt(record, binary_sha256, launch) else None


# --- The subject (§2.1 "Binary", §4.4 check 1) ----------------------------------------------


@dataclass(frozen=True)
class JailedSubject:
    path: str
    sha256: str


# Native Windows has none of these flags (nor ``dir_fd``): ``None`` makes every open fail closed.
if os.name != "nt":
    _WALK = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
else:
    _WALK = None


def root_owned_digest(path: str) -> str:
    """sha256 of ``path`` after its whole ownership chain is checked: every component from
    ``/`` to the executable owned by root and not group- or other-writable (``seat_subject``'s
    owned-directory check, applied to each), no symlink anywhere, the file regular. Raises
    :class:`JailRefused`."""
    from .seat_subject import _require_owned_directory

    _require(os.path.isabs(path) and posixpath.normpath(path) == path, "path not normal")
    parts = [part for part in path.split("/") if part]
    _require(bool(parts) and not any(part in {".", ".."} for part in parts))
    try:
        directory = os.open("/", _WALK)
    except OSError as exc:
        raise JailRefused("root unavailable") from exc
    try:
        try:
            _require_owned_directory(directory, frozenset({0}))
            for part in parts[:-1]:
                child = os.open(part, _WALK, dir_fd=directory)
                os.close(directory)
                directory = child
                _require_owned_directory(directory, frozenset({0}))
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                                 | os.O_CLOEXEC, dir_fd=directory)
        except Exception as exc:  # noqa: BLE001 - ExecutableDependencyError and OSError
            raise JailRefused("ownership chain") from exc
        try:
            info = os.fstat(descriptor)
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                     and not info.st_mode & 0o022, "unsafe executable")
            digest = sha256()
            while chunk := os.read(descriptor, 1 << 20):
                digest.update(chunk)
            after = os.fstat(descriptor)
            _require((after.st_ino, after.st_size, after.st_mtime_ns)
                     == (info.st_ino, info.st_size, info.st_mtime_ns), "changed while read")
            return digest.hexdigest()
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def resolve_subject(env: Mapping[str, str] | None = None) -> JailedSubject:
    """The jailed Grok subject: ``_resolved_jail_subject``'s executable (standalone or
    managed), with no dependency projection (the profile declares none), after the
    root-owned chain walk. Raises ``SeatSandboxRefused(grok_tool_surface_unverified)``."""
    from .panel_invoker import _resolved_jail_subject
    from .seat_subject import _names_managed_root

    try:
        subject, dependency = _resolved_jail_subject(_profile.LEG, dict(os.environ if env is None else env))
        if dependency is not None:
            close = getattr(dependency, "close", None)
            if getattr(dependency, "_jailcore_owned", False) and callable(close):
                close()
            raise JailRefused("a dependency projection is refused")
        _require(subject.subject_path is not None)
        if subject.source == "managed_image":
            _require(subject.binary_sha256 is not None, "managed image digest")
            return JailedSubject(str(subject.subject_path), subject.binary_sha256)
        _require(subject.source == "standalone" and not _names_managed_root(subject.subject_path),
                 "Grok subject source")
        path = os.path.realpath(str(subject.subject_path))
        return JailedSubject(path, root_owned_digest(path))
    except Exception as exc:  # noqa: BLE001
        raise _refused() from exc


def precondition_code() -> str | None:
    """L6 for the registered Grok profile (§4.2, provisional): ``None`` only when all five
    eligibility conditions hold for the resolved subject and its jailed receipt matches the
    record; otherwise the fixed refusal. Reads no unjailed receipt."""
    try:
        subject = resolve_subject()
        if eligibility(subject.sha256) is not None:
            return REFUSED
        launch = _expected_launch(subject.sha256)
        if launch is None or jail_receipt_matches(subject.sha256, launch) is None:
            return REFUSED
    except Exception:  # noqa: BLE001
        return REFUSED
    return None


# --- The mark and the final verifier (§4.4) -------------------------------------------------


@dataclass(frozen=True)
class MeasurementReservation:
    """What SL-4's ledger hands the jailed measurement: one immutable reservation."""

    grant_id: str
    reservation_id: str
    label: str
    image_sha256: str
    budget: int
    grant_dir: str


@dataclass(frozen=True)
class JailLaunchContext:
    """The mark :func:`verify_jail_launch_context` issues. The jailed spawn admits a Grok
    argv only with a mark for that exact argv, jail, cwd, proxy and holder."""

    mode: str
    command: tuple[str, ...]
    cwd: str
    owner_sha256: str
    jail_id: int
    holder: int
    proxy_socket: str
    binary_sha256: str
    launch_digest: str
    jail_context_digest: str
    surface_digest: str | None = None
    reservation_id: str | None = None
    issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.issuer is not _ISSUER:
            raise TypeError("a jail launch context is issued only by verify_jail_launch_context")


def _owner_sha256(jail) -> str:
    return sha256("\0".join(jail.process_owner).encode("utf-8", "surrogateescape")).hexdigest()


def admits(context: object, jail, command, cwd) -> bool:
    """Does ``context`` admit spawning ``command`` in ``jail`` at ``cwd`` now?"""
    return (isinstance(context, JailLaunchContext) and context.issuer is _ISSUER
            and context.jail_id == id(jail) and context.owner_sha256 == _owner_sha256(jail)
            and context.command == tuple(str(word) for word in command)
            and context.cwd == str(cwd))


# The bwrap options the owner argv may carry, with their operand counts; a destination is
# an operation's last operand. An unknown option refuses.
_ARITY = MappingProxyType({
    "--die-with-parent": 0, "--unshare-pid": 0, "--unshare-ipc": 0, "--unshare-uts": 0,
    "--unshare-cgroup-try": 0, "--unshare-cgroup": 0, "--unshare-net": 0, "--clearenv": 0,
    "--new-session": 0, "--as-pid-1": 0, "--unshare-user": 0, "--unshare-user-try": 0,
    "--cap-drop": 1, "--cap-add": 1, "--perms": 1, "--dir": 1, "--tmpfs": 1, "--proc": 1,
    "--dev": 1, "--mqueue": 1, "--remount-ro": 1, "--chdir": 1, "--seccomp": 1,
    "--info-fd": 1, "--block-fd": 1, "--sync-fd": 1, "--unsetenv": 1, "--size": 1,
    "--uid": 1, "--gid": 1, "--hostname": 1, "--argv0": 1,
    "--ro-bind": 2, "--bind": 2, "--dev-bind": 2, "--ro-bind-try": 2, "--bind-try": 2,
    "--dev-bind-try": 2, "--symlink": 2, "--file": 2, "--bind-data": 2, "--ro-bind-data": 2,
    "--setenv": 2, "--chmod": 2,
})
_MOUNTS = frozenset({"--dir", "--tmpfs", "--proc", "--dev", "--mqueue", "--ro-bind", "--bind",
                     "--dev-bind", "--ro-bind-try", "--bind-try", "--dev-bind-try", "--symlink",
                     "--file", "--bind-data", "--ro-bind-data", "--chmod"})


def _operations(owner) -> list[tuple[int, str, tuple[str, ...]]]:
    words = [str(word) for word in owner]
    _require(bool(words) and Path(words[0]).name == "bwrap", "owner is not bwrap")
    index, found = 1, []
    while index < len(words):
        option = words[index]
        _require(option in _ARITY, f"unknown owner option {option}")
        count = _ARITY[option]
        operands = tuple(words[index + 1:index + 1 + count])
        _require(len(operands) == count, "truncated owner option")
        found.append((index, option, operands))
        index += 1 + count
    return found


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _check_mount_policy(jail) -> None:
    """§2.3 and §2.4 on the actual owner argv: exactly the ordered list, contiguous and
    last among the mounts, after the builder's tree, home and out binds; no other mount at,
    below or above any of its destinations (the builder's home and tree binds and the root
    remount excepted); every destination absolute, normalised and free of symlinks in its
    host source path."""
    from .seat_jail import HOST_HOME_DIRNAME, HOST_OUT_DIRNAME
    from .seat_route_contract import OwnerPaths

    home = str(Path(jail.review_dir) / HOST_HOME_DIRNAME)
    expected = list(_profile._owner_binds(OwnerPaths(
        tree=jail.tree_dir, home=home, out=str(Path(jail.review_dir) / HOST_OUT_DIRNAME),
        provider=jail.provider_path, bundle_fd=str(jail.bundle_fd),
        instructions_fd=str(jail.instructions_fd), token_fd=None,
        seccomp_fd=str(jail.seccomp_fd), provider_config=jail.gemini_config_dir or None,
        egress_ca=jail.egress_ca or None, egress_proxy=jail.egress_proxy or None)))
    words = [str(word) for word in jail.process_owner]
    starts = [index for index in range(len(words) - len(expected) + 1)
              if words[index:index + len(expected)] == expected]
    _require(len(starts) == 1, "the ordered mount list is not exactly present")
    start, end = starts[0], starts[0] + len(expected)
    operations = _operations(words)
    destinations = [operands[-1] for index, option, operands in operations
                    if start <= index < end and option in _MOUNTS]
    for destination in destinations:
        _require(posixpath.isabs(destination)
                 and posixpath.normpath(destination) == destination, "destination not normal")
    allowed_ancestors = {"/seat", _profile.SEAT_HOME, _profile.SEAT_TREE}
    for index, option, operands in operations:
        if start <= index < end:
            continue
        if option in _MOUNTS:
            target = operands[-1]
            for destination in destinations:
                if _within(target, destination):
                    raise JailRefused("a shadow mount over the protected list")
                if _within(destination, target) and not (
                        target in allowed_ancestors and index < start):
                    raise JailRefused("a mount above the protected list")
            if index >= end:
                raise JailRefused("a mount after the protected list")
        elif option == "--remount-ro":
            _require(operands[0] == "/" and index >= end, "an unexpected remount")
    for source in (jail.gemini_config_dir, jail.egress_ca, home, jail.tree_dir,
                   _profile.masks_source(jail.gemini_config_dir, _profile.MASK_FILE),
                   _profile.masks_source(jail.gemini_config_dir, _profile.MASK_DIRECTORY)):
        _require(bool(source) and os.path.realpath(source) == os.path.abspath(source),
                 "a symlinked source")


def _open_regular(directory: int, name: str, *, mode: int, limit: int = 1 << 20) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == mode
                 and info.st_uid == os.getuid() and info.st_size <= limit, f"{name} unsafe")
        return os.read(descriptor, limit + 1)
    finally:
        os.close(descriptor)


def _check_staged_bytes(jail, credential, proxy) -> None:
    """Check 3's per-launch bytes, on the staged objects the bind projects: the staged
    directory holds exactly its table's entries; the config is the pinned bytes; the two
    credential files are the staged copy's; the CA is this launch's proxy's; the mask
    sources are an empty 0444 file and an empty 0555 directory."""
    from . import seat_grok_credential as cred
    from .seat_jail import open_dir_nofollow

    _require(credential is not None and isinstance(credential, cred.GrokSeatCredential),
             "no staged credential")
    _require(os.path.abspath(str(credential.config_dir)) == jail.gemini_config_dir,
             "the credential is not this jail's staged directory")
    staged = open_dir_nofollow(jail.gemini_config_dir)
    try:
        info = os.fstat(staged)
        _require(stat.S_IMODE(info.st_mode) == 0o555 and info.st_uid == os.getuid())
        _require(set(os.listdir(staged)) == set(cred.STAGED_ENTRIES), "staged entries")
        config = _open_regular(staged, cred.CONFIG_FILE_NAME, mode=0o444)
        _require(sha256(config).hexdigest() == _gts.SEAT_CONFIG_SHA256, "config bytes")
        auth = _open_regular(staged, cred.AUTH_FILE_NAME, mode=0o444)
        agent = _open_regular(staged, cred.AGENT_ID_FILE_NAME, mode=0o444)
        _require(cred.credential_digest(auth, agent) == credential.digest, "credential bytes")
        for name in cred.MOUNT_POINT_FILES:
            _require(_open_regular(staged, name, mode=0o444) == b"", f"{name} not empty")
        for name in cred.MOUNT_POINT_DIRS:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=staged)
            try:
                _require(os.listdir(child) == [], f"{name} not empty")
            finally:
                os.close(child)
    finally:
        os.close(staged)
    parent = open_dir_nofollow(os.path.dirname(jail.egress_ca))
    try:
        ca = _open_regular(parent, os.path.basename(jail.egress_ca), mode=0o444)
    finally:
        os.close(parent)
    _require(sha256(ca).hexdigest() == proxy.ca_sha256, "the CA is not this proxy's")
    masks = open_dir_nofollow(posixpath.join(os.path.dirname(jail.gemini_config_dir),
                                             _profile.HOST_GROK_MASKS_DIRNAME))
    try:
        _require(_open_regular(masks, _profile.MASK_FILE, mode=0o444) == b"", "file mask")
        empty = os.open(_profile.MASK_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                        | os.O_CLOEXEC, dir_fd=masks)
        try:
            _require(stat.S_IMODE(os.fstat(empty).st_mode) == 0o555
                     and os.listdir(empty) == [], "directory mask")
        finally:
            os.close(empty)
    finally:
        os.close(masks)


def _check_mount_points(jail) -> None:
    """The stubs bwrap mounts over (§2.4 "Mount points"): present with the table's type,
    never a link, in seat-home and the tree copy."""
    from .seat_jail import HOST_HOME_DIRNAME

    for root, masks in ((Path(jail.review_dir) / HOST_HOME_DIRNAME, _profile.HOME_MASKS),
                        (Path(jail.tree_dir), _profile.TREE_MASKS)):
        for path, treatment in masks:
            top = path.split("/", 1)[0]
            info = os.lstat(root / top)
            directory = treatment == _profile.MASKED_DIRECTORY or "/" in path
            _require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                     and not stat.S_ISLNK(info.st_mode), f"mount point {top}")


def _check_proxy(proxy, holder: int, *, budget: int | None) -> None:
    from . import seat_egress_proxy
    from .seat_uid import holder_pid_from_prefix

    _require(proxy is not None and proxy.process.poll() is None, "proxy not live")
    _require(proxy.allowlist_id == _profile.GROK_PROFILE.allowlist_id, "allow-list")
    _require(proxy.allowlist_digest == seat_egress_proxy.allowlist_ref(
        proxy.allowlist_id).content_digest, "allow-list digest")
    _require(proxy.request_budget == budget and (budget is None or type(budget) is int),
             "budget")
    from .panel_invoker import _EGRESS_LAUNCH_PREFIX

    prefix = tuple(_EGRESS_LAUNCH_PREFIX.get())
    _require(bool(prefix) and holder_pid_from_prefix(prefix) == holder, "holder")
    _require(_gts.bridged_to(prefix, proxy), "the holder does not bridge to this proxy")


def verify_jail_launch_context(jail, *, mode: str, proxy, holder: int, cwd, command,
                               credential=None,
                               measurement: "JailedMeasurementLaunch | None" = None,
                               ) -> JailLaunchContext:
    """The one final verifier (§4.4), run at the jailed spawn boundary against the objects
    about to be spawned. Every failure is ``grok_tool_surface_unverified`` before any
    process starts."""
    try:
        return _verify(jail, mode=mode, proxy=proxy, holder=holder, cwd=cwd, command=command,
                       credential=credential, measurement=measurement)
    except Exception as exc:  # noqa: BLE001 - every failure is the one code
        raise _refused() from exc


def _verify(jail, *, mode, proxy, holder, cwd, command, credential, measurement):
    from .panel_invoker import _grok_argv_digest
    from .seat_jail import SeatJail
    from .seat_subject import _names_managed_root, managed_grok_image_digest

    _require(mode in MODES and isinstance(jail, SeatJail) and jail.leg == _profile.LEG)
    command = tuple(str(word) for word in command)
    # 1. Binary: the bound source, whole chain root-owned, hashed now; no projection.
    _require(not jail.dependency_destinations and jail.dependency is None
             and not jail.dependency_mount_args, "a dependency projection")
    _require(jail.provider_argv0 == f"/seat/bin/{_profile.LEG}")
    _require(os.path.realpath(jail.provider_path) == jail.provider_path, "symlinked subject")
    path = Path(jail.provider_path)
    binary = (managed_grok_image_digest(path) if _names_managed_root(path)
              else root_owned_digest(jail.provider_path))
    # 4. Cwd and argv: exactly the production staged form.
    _require(str(cwd) == SEAT_CWD, "cwd")
    _require(command == production_command(jail.provider_argv0), "argv")
    _require(_grok_argv_digest(list(command)) == staged_argv_digest(), "argv digest")
    # 3. Projections and masks, then the per-launch bytes.
    _check_mount_policy(jail if mode == "board" else dataclasses.replace(
        jail, process_owner=production_owner(jail, measurement=True)))
    _check_mount_points(jail)
    _check_staged_bytes(jail, credential, proxy)
    # 2. Owner argv: the normalised actual launch digest is the expected production value.
    launch = launch_digest(jail, command, measurement=mode == "measurement")
    expected = _expected_launch(binary)
    _require(expected is not None and launch == expected, "launch digest")
    surface_digest = reservation_id = None
    if mode == "board":
        # 5 (board): no budget; all five conditions; the jailed receipt re-resolved now.
        _check_proxy(proxy, holder, budget=None)
        _require(eligibility(binary) is None, "eligibility")
        record = jail_receipt_matches(binary, launch)
        _require(record is not None, "receipt")
        assert record is not None
        surface_digest = record.surface_digest
    else:
        _require(isinstance(measurement, JailedMeasurementLaunch)
                 and measurement.issuer is _ISSUER, "no prepared measurement")
        assert measurement is not None
        reservation = measurement.reservation
        _require(reservation.image_sha256 == binary, "the grant's image")
        _require(reservation.budget in (0, 1), "budget")
        _check_proxy(proxy, holder, budget=reservation.budget)
        _require(eligibility(binary, through=4) is None, "eligibility")
        # r7 (§4.4, §4.5 M4): verified here, not consumed. Only the spawn hook of M5,
        # :func:`consume_admission`, consumes it, after the qualification check and the
        # identity probe inside ``launch_provider``.
        _require(_admission_binding(reservation, jail, proxy, holder, command, binary)
                 == dict(measurement.admission), "the admission does not bind this launch")
        reservation_id = reservation.reservation_id
    return JailLaunchContext(
        mode=mode, command=command, cwd=str(cwd), owner_sha256=_owner_sha256(jail),
        jail_id=id(jail), holder=int(holder), proxy_socket=str(proxy.socket),
        binary_sha256=binary, launch_digest=launch,
        jail_context_digest=jail_context_digest(binary), surface_digest=surface_digest,
        reservation_id=reservation_id, issuer=_ISSUER)


# --- The jailed measurement (§5.1, the verifier's measurement mode) -------------------------


@dataclass(frozen=True)
class JailedMeasurementLaunch:
    """What :func:`prepare_measurement` returns: the reservation, the scan values of the
    staged copy (memory only; the reader scans before it retains anything and drops this
    object once the result is written) and the recorded, not yet consumed, admission."""

    reservation: MeasurementReservation
    scan_values: object = field(repr=False, compare=False)
    admission: Mapping[str, object] = field(compare=False)
    issuer: object = field(default=None, repr=False, compare=False)
    #: The operator's descriptor of the admitted sink, opened at M1 before the M2 handoff
    #: and held through the launch: M2's parent check and the M5 hook read the sink
    #: through it, and check that the path still names the same inode.
    sink_fd: int | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.issuer is not _ISSUER:
            raise TypeError("a jailed measurement launch is issued only by prepare_measurement")


def close_measurement(measurement: object) -> None:
    """Close the sink descriptor a prepared measurement holds (idempotent)."""
    descriptor = getattr(measurement, "sink_fd", None)
    if isinstance(measurement, JailedMeasurementLaunch) and descriptor is not None:
        object.__setattr__(measurement, "sink_fd", None)
        with contextlib.suppress(OSError):
            os.close(descriptor)


# Native Windows has none of these flags (nor ``dir_fd``): ``None`` makes every open fail closed.
if os.name != "nt":
    _PATH_WALK = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    _DIR_READ = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
else:
    _PATH_WALK = _DIR_READ = None


def open_dir_chain(path: str) -> int:
    """A readable descriptor of the directory ``path``, opened one component at a time
    from ``/`` without following a link anywhere. The sink's ancestors are the operator's
    private review directories; that ancestry is trusted (an operator-side process can
    always act as the operator), and every check below binds the inode, not the name."""
    _require(os.path.isabs(path) and posixpath.normpath(path) == path, "path not normal")
    parts = [part for part in path.split("/") if part]
    _require(bool(parts) and not any(part in {".", ".."} for part in parts))
    current = os.open("/", _PATH_WALK)
    try:
        for part in parts[:-1]:
            child = os.open(part, _PATH_WALK, dir_fd=current)
            os.close(current)
            current = child
        return os.open(parts[-1], _DIR_READ, dir_fd=current)
    finally:
        os.close(current)


def _sink_view(descriptor: int, admitted) -> os.stat_result:
    info = os.fstat(descriptor)
    _require(stat.S_ISDIR(info.st_mode) and [info.st_dev, info.st_ino] == list(admitted),
             "the sink is not the admitted inode")
    return info


def _identity(path: str) -> list[int]:
    info = os.lstat(path)
    return [info.st_dev, info.st_ino]


def _netns(holder: int) -> int:
    return os.stat(f"/proc/{int(holder)}/ns/net").st_ino


def _route_steps_except_l6() -> None:
    """§5.1 item 1: L0 is the caller's staged tree; L3, L5, L7 and L8's verdict (read, never
    run) for the production qualification key."""
    from . import sandbox_egress, seat_egress_proxy, seat_jail

    _require(seat_jail.seat_sandbox_capable() is None, "L3")
    _require(_profile.GROK_PROFILE.credential_present(), "L5")
    _require(sandbox_egress.egress_required(), "L7 opt-out")
    _require(seat_egress_proxy.unavailable_code() is None, "L7")
    seat_egress_proxy.allowlist_ref(_profile.GROK_PROFILE.allowlist_id)
    _require(seat_jail.pass_record_verdict(_profile.qualification_key())[0] is True, "L8")


def _admission_binding(reservation, jail, proxy, holder, command, binary) -> dict[str, object]:
    from .panel_invoker import _grok_argv_digest

    sink = sink_source(_home_of(jail))
    return {
        "schema": ADMISSION_SCHEMA, "grant": reservation.grant_id,
        "reservation": reservation.reservation_id, "label": reservation.label,
        "image_sha256": binary, "argv_digest": _grok_argv_digest(list(command)),
        "cwd": SEAT_CWD, "staged": _identity(jail.gemini_config_dir), "sink": _identity(sink),
        "holder": int(holder), "netns": _netns(holder), "proxy_socket": str(proxy.socket),
        "budget": reservation.budget,
    }


def prepare_measurement(reservation: MeasurementReservation, seat, *, proxy, holder: int,
                        command, check_route: bool = True) -> JailedMeasurementLaunch:
    """§5.1 without a route bypass: every route step but L6 (item 1); the seat composed by
    the production builder path with the sink bind as its one owner difference (items 2-3,
    the caller's ``seat``, whose jail is :func:`measurement_owner`'s); the declared proxy
    difference; the production ``launch_digest``; the admission recorded, not consumed
    (item 4). Refuses ``grok_tool_surface_unverified``."""
    try:
        _require(isinstance(reservation, MeasurementReservation))
        _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", reservation.reservation_id)
                 is not None, "reservation id")
        if check_route:
            _route_steps_except_l6()
        jail = seat.jail
        _require(eligibility(reservation.image_sha256, through=4) is None, "conditions 1-4")
        sink = sink_source(_home_of(jail))
        launch = launch_digest(jail, command, measurement=True)
        _require(launch == _expected_launch(reservation.image_sha256), "launch digest")
        _require(proxy.request_budget == reservation.budget, "the proxy's budget")
        admission = _admission_binding(reservation, jail, proxy, holder, command,
                                       reservation.image_sha256)
        descriptor = open_dir_chain(sink)
        try:
            info = _sink_view(descriptor, admission["sink"])
            _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
                     and not os.listdir(descriptor), "the sink is not fresh")
            return JailedMeasurementLaunch(reservation, seat.credential.scan_values,
                                           MappingProxyType(admission), issuer=_ISSUER,
                                           sink_fd=descriptor)
        except BaseException:
            os.close(descriptor)
            raise
    except Exception as exc:  # noqa: BLE001
        raise _refused() from exc


def consume_admission(measurement, jail, proxy, holder, command, binary) -> None:
    """The spawn hook of §4.5 step M5, the last step before ``Popen``: the recorded
    admission, re-derived from the actual objects, with the sink still empty, is consumed
    atomically (``O_CREAT|O_EXCL``) in the grant directory, once. Only a
    :class:`JailedMeasurementLaunch` that :func:`prepare_measurement` issued is consumed.
    Raises :class:`JailRefused`; once the file exists the charge stands, whatever follows."""
    from .seat_jail import open_dir_nofollow

    _require(isinstance(measurement, JailedMeasurementLaunch) and measurement.issuer is _ISSUER,
             "no prepared measurement")
    reservation = measurement.reservation
    actual = _admission_binding(reservation, jail, proxy, holder, command, binary)
    _require(actual == dict(measurement.admission), "the admission does not bind this launch")
    # Through the operator's descriptor of the admitted inode (the sink is the seat's since
    # M2); the path, re-checked here, still names that inode.
    _require(measurement.sink_fd is not None, "no sink descriptor")
    _sink_view(measurement.sink_fd, actual["sink"])
    _require(not os.listdir(measurement.sink_fd), "the sink is not empty")
    directory = open_dir_nofollow(reservation.grant_dir)
    try:
        info = os.fstat(directory)
        _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                 "grant directory")
        try:
            descriptor = os.open(admission_name(reservation.reservation_id),
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                 | os.O_CLOEXEC, 0o600, dir_fd=directory)
        except FileExistsError as exc:
            raise JailRefused("the admission was consumed") from exc
        try:
            os.write(descriptor, _canonical(actual) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def admission_name(reservation_id: str) -> str:
    """``admission-<reservation id>`` in the grant directory: present only once the M5
    hook ran (§4.5, "The rule that makes the order safe")."""
    return f"admission-{reservation_id}"


def admission_state(reservation: MeasurementReservation) -> str:
    """``present`` (a regular file of the operator's), ``absent``, or ``unknown`` when the
    grant directory or the entry cannot be read or is not that file."""
    from .seat_jail import open_dir_nofollow

    try:
        directory = open_dir_nofollow(reservation.grant_dir)
    except OSError:
        return "unknown"
    try:
        info = os.stat(admission_name(reservation.reservation_id), dir_fd=directory,
                       follow_symlinks=False)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    finally:
        os.close(directory)
    return "present" if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() else "unknown"


def admission_consumed(reservation: MeasurementReservation) -> bool:
    """The charge decision: was the admission consumed? Only a positive ``absent`` is proof
    that no provider process started for it (§4.5); any doubt is ``True``."""
    return admission_state(reservation) != "absent"


def admission_present(reservation: MeasurementReservation) -> bool:
    """The strict post-run check: the admission file is positively present. Any doubt is
    ``False``, so nothing is read and the launch does not succeed (the charge stays)."""
    return admission_state(reservation) == "present"


# --- The sink probe (§4.5 step M2) and the sink reader, run in H ---------------------------

_SINK_TIMEOUT_S = 60
_SINK_PROBE_PREFIX = ".sink-probe-"
_SINK_MISSING, _SINK_AMBIGUOUS = 4, 5


def _in_h_argv(holder_pid: int, verb: str, *args: str) -> list[str]:
    """``nsenter`` into H as H-root, then this module's helper ``verb``."""
    from . import seat_uid

    return ["/usr/bin/nsenter", "-t", str(int(holder_pid)), "-U", "-m",
            "--preserve-credentials",
            *seat_uid.trusted_module_argv("phase_loop_runtime.grok_jail_surface", verb, *args)]


def probe_sink(holder_pid: int, seat_id: int, sink: str, *,
               measurement: "JailedMeasurementLaunch") -> tuple[int, int]:
    """§4.5 step M2. In H, the H-root helper opens the sink one component at a time without
    following a link and requires the **admitted** inode (the admission's ``sink`` binding),
    an empty H-root-owned 0700 directory, before it changes anything; it then hands that
    inode to the seat UID (``seat_id:seat_id``, still 0700) and runs this module's
    ``sink-probe`` verb as the dropped UID (``seat_jail.setpriv_drop(seat_id)``,
    ``trusted_module_argv``) on the same descriptor. As that UID the probe creates
    ``.sink-probe-<16 hex>`` exclusively, writes 32 random bytes, fsyncs, reads them back and
    unlinks the file. Passes only on exit 0 within 60 s; the parent then finds, by path and
    through the descriptor it opened at M1, the admitted inode, seat-owned and 0700, and
    empty. Returns ``(device, inode)``; anything else is ``grok_tool_surface_unverified``
    with nothing spawned and nothing consumed."""
    import subprocess

    from . import seat_uid

    try:
        _require(isinstance(measurement, JailedMeasurementLaunch)
                 and measurement.issuer is _ISSUER and measurement.sink_fd is not None,
                 "no prepared measurement")
        admitted = [int(value) for value in measurement.admission["sink"]]
        done = subprocess.run(_in_h_argv(holder_pid, "sink-handoff", str(sink), str(int(seat_id)),
                                         str(admitted[0]), str(admitted[1])),
                              stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=_SINK_TIMEOUT_S, env=seat_uid._pythonpath_env())
        _require(done.returncode == 0, "the sink probe failed")
        reported = _loads(done.stdout)
        _require(type(reported) is dict and set(reported) == {"device", "inode"}
                 and [reported["device"], reported["inode"]] == admitted, "report")
        info = os.lstat(sink)
        _require(stat.S_ISDIR(info.st_mode) and [info.st_dev, info.st_ino] == admitted
                 and info.st_uid != os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                 "the sink is not the admitted, seat-owned inode")
        _sink_view(measurement.sink_fd, admitted)
        _require(not os.listdir(measurement.sink_fd), "the sink is not empty")
        return info.st_dev, info.st_ino
    except Exception as exc:  # noqa: BLE001 - a helper that cannot run is a failure
        raise _refused() from exc


def read_sink_in_h(holder_pid: int, seat_id: int, sink: str) -> bytes:
    """The one ``<group>/<session>/tool_definitions.json`` under the sink, read in H as
    H-root with the TS contract §5.5 rules (the file the seat UID's). Raises
    ``grok_tool_surface.ArtifactRefused``: ``artifact_missing`` or ``artifact_ambiguous``,
    and the latter for a helper that cannot run."""
    import subprocess

    from . import seat_uid

    try:
        done = subprocess.run(_in_h_argv(holder_pid, "sink-read", str(sink), str(int(seat_id))),
                              stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=_SINK_TIMEOUT_S, env=seat_uid._pythonpath_env())
    except Exception as exc:  # noqa: BLE001
        raise _gts.ArtifactRefused("artifact_ambiguous") from exc
    if done.returncode == _SINK_MISSING:
        raise _gts.ArtifactRefused("artifact_missing")
    if done.returncode != 0 or len(done.stdout) > _gts.DEFINITIONS_MAX_BYTES:
        raise _gts.ArtifactRefused("artifact_ambiguous")
    return done.stdout


def _sink_handoff_main(sink: str, seat_text: str, device_text: str, inode_text: str) -> int:
    """As H-root: the sink, opened one component at a time without following a link, must
    be the admitted inode and an empty H-root-owned 0700 directory **before** anything is
    changed. It is then handed to the seat UID (``n:n``, 0700, as ``seat_uid.handoff`` would)
    and the probe runs as that UID on this descriptor (seat-home is not the seat's to
    traverse before the launch)."""
    from .seat_jail import setpriv_drop
    from .seat_uid import trusted_module_argv

    try:
        seat_id = int(seat_text)
        descriptor = open_dir_chain(sink)
        info = os.fstat(descriptor)
        if (not stat.S_ISDIR(info.st_mode) or [info.st_dev, info.st_ino]
                != [int(device_text), int(inode_text)] or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or os.listdir(descriptor)):
            return 3
        os.fchown(descriptor, seat_id, seat_id)
        os.fchmod(descriptor, 0o700)
        after = os.fstat(descriptor)
        if (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)) != (seat_id, seat_id, 0o700):
            return 3
        os.set_inheritable(descriptor, True)
        argv = [*setpriv_drop(seat_id),
                *trusted_module_argv("phase_loop_runtime.grok_jail_surface", "sink-probe",
                                     str(descriptor))]
        os.execv(argv[0], argv)
    except (OSError, ValueError):
        return 3
    return 3  # pragma: no cover - execv does not return


def _sink_probe_main(descriptor_text: str) -> int:
    """As the dropped seat UID, on the inherited sink descriptor (§4.5 M2)."""
    import secrets

    try:
        directory = int(descriptor_text)
        info = os.fstat(directory)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_gid != os.getgid() or stat.S_IMODE(info.st_mode) != 0o700
                or os.listdir(directory)):
            return 3
        name = _SINK_PROBE_PREFIX + secrets.token_hex(8)
        data = secrets.token_bytes(32)
        written = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                          | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            if os.write(written, data) != len(data):
                return 3
            os.fsync(written)
        finally:
            os.close(written)
        read = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
        try:
            back = os.read(read, len(data) + 1)
        finally:
            os.close(read)
        os.unlink(name, dir_fd=directory)
        if back != data or os.listdir(directory):
            return 3
    except (OSError, ValueError):
        return 3
    sys.stdout.write(json.dumps({"device": info.st_dev, "inode": info.st_ino}))
    return 0


def _sink_read_main(sink: str, seat_text: str) -> int:
    try:
        directory = open_dir_chain(sink)
    except (OSError, JailRefused):
        return _SINK_AMBIGUOUS
    try:
        raw = _gts.read_definitions(directory, owner_uid=int(seat_text))
    except _gts.ArtifactRefused as refusal:
        return _SINK_MISSING if refusal.status == "artifact_missing" else _SINK_AMBIGUOUS
    except (OSError, ValueError):
        return _SINK_AMBIGUOUS
    finally:
        os.close(directory)
    sys.stdout.buffer.write(raw)
    return 0


# --- The refresh after-check, run where the seat's files are readable ----------------------

_AFTER_FINDING = 3


def after_check_in_h(holder_pid: int, seat_home: str) -> str | None:
    """``grok_seat_token_refreshed_in_jail`` if a credential-shaped file appeared in
    seat-home, checked as H-root (the operator inside the seat's user namespace), where the
    seat-owned files are readable. A helper that cannot run is a finding (fail closed)."""
    import subprocess

    from . import seat_uid

    argv = ["/usr/bin/nsenter", "-t", str(int(holder_pid)), "-U", "-m",
            "--preserve-credentials",
            *seat_uid.trusted_module_argv("phase_loop_runtime.grok_jail_surface", "after",
                                          str(seat_home))]
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
                              env=seat_uid._pythonpath_env())
    except (OSError, subprocess.SubprocessError):
        return "grok_seat_token_refreshed_in_jail"
    return None if done.returncode == 0 else "grok_seat_token_refreshed_in_jail"


def _after_main(seat_home: str) -> int:
    from . import seat_grok_credential as cred
    if cred._O_DIR is None:
        return _AFTER_FINDING

    home = os.path.abspath(seat_home)
    if not os.path.lexists(home):
        # Run before cleanup: a seat-home H cannot see is not a clean pass (review N-2).
        return _AFTER_FINDING
    try:
        root = os.open(home, cred._O_DIR)
    except OSError:
        return _AFTER_FINDING
    try:
        return _AFTER_FINDING if cred._scan_dir(root, 0, [cred._AFTER_MAX_ENTRIES]) else 0
    except OSError:
        return _AFTER_FINDING
    finally:
        os.close(root)


__all__ = [
    "CONDITIONS", "ENFORCEMENT", "JAIL_CONTEXT", "JailLaunchContext", "JailedMeasurementLaunch",
    "JailedSubject", "JailedSurface", "MeasurementReservation", "admission_consumed",
    "admission_name", "admission_present", "admission_state", "admits", "close_measurement",
    "open_dir_chain", "after_check_in_h", "consume_admission", "eligibility",
    "jail_context_digest", "launch_digest", "measurement_owner", "precondition_code",
    "prepare_measurement", "probe_sink", "production_owner", "read_sink_in_h",
    "resolve_record", "resolve_subject",
    "staged_admission", "verify_jail_launch_context", "write_jail_receipt",
]


if __name__ == "__main__":  # pragma: no cover - run in H by the helpers above
    if len(sys.argv) == 3 and sys.argv[1] == "after":
        raise SystemExit(_after_main(sys.argv[2]))
    if len(sys.argv) == 6 and sys.argv[1] == "sink-handoff":
        raise SystemExit(_sink_handoff_main(*sys.argv[2:6]))
    if len(sys.argv) == 3 and sys.argv[1] == "sink-probe":
        raise SystemExit(_sink_probe_main(sys.argv[2]))
    if len(sys.argv) == 4 and sys.argv[1] == "sink-read":
        raise SystemExit(_sink_read_main(sys.argv[2], sys.argv[3]))
    raise SystemExit(errno.EINVAL)
